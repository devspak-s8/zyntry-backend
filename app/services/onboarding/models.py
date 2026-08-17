from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.services.integrations.definitions import integration_registry


@dataclass
class OnboardingModelResponse:
    text: str
    proposed_intent: str | None = None
    proposed_data: dict[str, Any] = field(default_factory=dict)
    suggested_actions: list[str] = field(default_factory=list)


class OnboardingModelProvider(Protocol):
    async def generate_step_response(
        self,
        user_message: str,
        current_state: str,
        current_config: dict[str, Any],
        history: list[dict[str, Any]],
    ) -> OnboardingModelResponse:
        ...


class FastOnboardingModelProvider:
    """Fast, deterministic, low-cost conversational onboarding provider with structured interpretation."""

    async def generate_step_response(
        self,
        user_message: str,
        current_state: str,
        current_config: dict[str, Any],
        history: list[dict[str, Any]],
    ) -> OnboardingModelResponse:
        msg_lower = user_message.lower().strip()

        # Check for direct intents and keywords
        if current_state == "onboarding_started":
            # Extract use case
            use_case = self._extract_use_case(msg_lower)
            return OnboardingModelResponse(
                text=(
                    f"That sounds great! Building for '{use_case}' is a great fit for Zyntry. "
                    "Will your application connect to your company's own internal data, "
                    "or will your end users connect their own external accounts (e.g., their own GitHub/Slack)?"
                ),
                proposed_intent="set_use_case",
                proposed_data={"use_case": use_case},
                suggested_actions=[
                    "End users connect their own accounts (Mode B)",
                    "Connect company data directly (Mode A)",
                    "Both (Hybrid)",
                ],
            )

        if current_state in ("discovering_use_case", "discovering_application_type"):
            mode = "end_user_oauth" if ("user" in msg_lower or "their own" in msg_lower or "byo" in msg_lower or "mode b" in msg_lower) else "zyntry_managed"
            app_type = "customer_facing_ai_app" if "user" in msg_lower else "internal_ai_agent"
            return OnboardingModelResponse(
                text=(
                    f"Got it! Configured as {'End-User Connection (Mode B)' if mode == 'end_user_oauth' else 'Zyntry-Managed Connection (Mode A)'}. "
                    "Which external integrations or services would you like to enable for your runtime? "
                    "(e.g., GitHub, Slack, Notion, PostgreSQL, MongoDB, Gmail)"
                ),
                proposed_intent="set_application_type",
                proposed_data={"application_type": app_type, "integration_mode": mode},
                suggested_actions=["GitHub", "Slack", "PostgreSQL", "Notion", "MongoDB"],
            )

        if current_state in ("selecting_integrations", "selecting_capabilities"):
            detected_integrations = self._detect_integrations(msg_lower)
            if not detected_integrations and current_config.get("integrations"):
                detected_integrations = current_config["integrations"]

            if not detected_integrations:
                detected_integrations = ["github"]

            return OnboardingModelResponse(
                text=(
                    f"Selected integrations: {', '.join(detected_integrations).upper()}. "
                    "We'll enable capabilities like repository search, file retrieval, and message retrieval. "
                    "Which AI model family would you prefer as primary? (e.g., GPT-4o, Claude 3.5 Sonnet, DeepSeek, or Fast Router)"
                ),
                proposed_intent="select_integrations",
                proposed_data={
                    "integrations": detected_integrations,
                    "capabilities": {slug: self._default_capabilities(slug) for slug in detected_integrations},
                },
                suggested_actions=["gpt-4o", "claude-3-5-sonnet", "deepseek-chat", "fast_router"],
            )

        if current_state in ("configuring_runtime", "confirming_configuration"):
            model = self._extract_model(msg_lower)
            return OnboardingModelResponse(
                text=(
                    f"Your runtime is ready to be configured with primary model '{model}' and balanced routing. "
                    "Please confirm to create your executable Zyntry runtime!"
                ),
                proposed_intent="confirm_configuration",
                proposed_data={
                    "model": model,
                    "provider": "openai" if "gpt" in model else "anthropic" if "claude" in model else "deepseek",
                    "routing_strategy": "balanced",
                    "environment": "development",
                },
                suggested_actions=["Confirm & Create Runtime", "Change Settings"],
            )

        # Default fallback response
        return OnboardingModelResponse(
            text="Understood. Let me update your configuration with these settings.",
            proposed_intent="general_update",
            proposed_data={},
            suggested_actions=["Continue", "Confirm Configuration"],
        )

    def _extract_use_case(self, msg: str) -> str:
        if "support" in msg:
            return "ai_customer_support"
        if "code" in msg or "developer" in msg or "github" in msg:
            return "developer_ai_assistant"
        if "knowledge" in msg or "rag" in msg or "search" in msg:
            return "knowledge_search_rag"
        if "agent" in msg:
            return "autonomous_ai_agent"
        return "general_ai_application"

    def _detect_integrations(self, msg: str) -> list[str]:
        found = []
        slugs = integration_registry.list_slugs()
        for slug in slugs:
            if slug in msg or slug.replace("_", " ") in msg:
                found.append(slug)
        if not found:
            if "git" in msg or "repo" in msg:
                found.append("github")
            if "chat" in msg or "channel" in msg:
                found.append("slack")
            if "doc" in msg or "wiki" in msg:
                found.append("notion")
            if "sql" in msg or "database" in msg:
                found.append("postgres")
        return found

    def _default_capabilities(self, slug: str) -> list[str]:
        defn = integration_registry.get(slug)
        if defn:
            return [c.slug for c in defn.capabilities if not c.is_write]
        return []

    def _extract_model(self, msg: str) -> str:
        if "claude" in msg or "sonnet" in msg:
            return "claude-3-5-sonnet-20241022"
        if "deepseek" in msg:
            return "deepseek-chat"
        if "gpt-4" in msg or "openai" in msg:
            return "gpt-4o"
        return "gpt-4o"


default_onboarding_model_provider = FastOnboardingModelProvider()
