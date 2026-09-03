from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.core.config import settings
from app.services.onboarding.intelligence import GeminiLLMProvider
from app.services.runtime_assistant.redaction import redact_sensitive
from app.services.runtime_assistant.schemas import RuntimeContext

logger = logging.getLogger(__name__)


def _strip_control_payload(text: str) -> str:
    """Remove raw tool/action JSON if a model ignores the response contract.

    Proposal details are rendered by the API metadata and the console card;
    leaking a ``pending_action`` object into the chat is confusing and can
    expose internal tool names. Keep the surrounding natural-language answer.
    """
    decoder = json.JSONDecoder()
    search_from = 0
    while True:
        match = re.search(r"(?is)(?:```(?:json)?\s*|\bjson\s*)?(\{)", text[search_from:])
        if not match:
            break
        brace_start = search_from + match.start(1)
        try:
            payload, consumed = decoder.raw_decode(text[brace_start:])
        except json.JSONDecodeError:
            search_from = brace_start + 1
            continue
        if not isinstance(payload, dict) or not any(
            key in payload for key in ("pending_action", "action_proposal", "tool_code")
        ):
            search_from = brace_start + consumed
            continue
        start = search_from + match.start()
        end = brace_start + consumed
        text = f"{text[:start].rstrip()}\n{text[end:].lstrip()}".strip()
        search_from = max(0, start - 1)
    return text.replace("```json", "").replace("```", "").strip()


class RuntimeAssistantResponder:
    """Turn verified control-plane context into a natural, contextual answer."""

    def __init__(self) -> None:
        provider = str(getattr(settings, "RUNTIME_ASSISTANT_PROVIDER", "google")).lower()
        self.model = str(getattr(settings, "RUNTIME_ASSISTANT_MODEL", "gemini-2.5-flash"))
        self.provider = GeminiLLMProvider(settings.GOOGLE_API_KEY) if provider in {"google", "gemini"} and settings.GOOGLE_API_KEY else None

    async def generate(
        self,
        *,
        user_message: str,
        context: RuntimeContext,
        decision: dict[str, Any],
        tool_evidence: list[dict[str, Any]],
        recent_messages: list[dict[str, str]],
        pending_action: dict[str, Any] | None = None,
    ) -> str | None:
        if self.provider is None:
            return None
        payload = redact_sensitive({
            "runtime": {
                "name": context.runtime.get("name"),
                "status": context.runtime.get("status"),
                "provider": context.runtime.get("provider"),
                "model": context.runtime.get("model"),
                "health": context.health,
                "deployment": context.deployment,
                "configuration": context.config,
                "knowledge_sources": context.knowledge_sources,
                "integrations": context.integrations,
            },
            "decision": decision,
            "verified_tool_evidence": tool_evidence,
            "pending_action": pending_action,
            "recent_conversation": recent_messages[-10:],
            "latest_user_message": user_message,
        })
        try:
            content, _ = await self.provider.generate(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are the Zyntry Runtime Assistant. Reply naturally to the user's actual message. "
                            "For greetings and ordinary conversation, converse normally and do not manufacture diagnostics. "
                            "For runtime questions, use only the supplied verified context and evidence. Never invent a status, "
                            "tool result, source, error, or completed action. If evidence is missing, say what you cannot verify. "
                            "Do not expose credentials, hidden reasoning, raw telemetry JSON, or internal decision objects. "
                            "Keep answers concise and actionable. Write operations require explicit confirmation. "
                            "If a pending action is supplied, describe it as a proposal and never as already applied."
                        ),
                    },
                    {"role": "user", "content": json.dumps(payload, default=str)},
                ],
                model=self.model,
                max_tokens=900,
                temperature=0.25,
            )
            return _strip_control_payload(content) or None
        except Exception:
            logger.exception("Runtime Assistant response generation failed; using verified fallback")
            return None
