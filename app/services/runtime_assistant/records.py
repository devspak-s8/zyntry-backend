from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.runtime_assistant import (
    RuntimeAssistantConversation,
    RuntimeAssistantEvidence,
    RuntimeAssistantMessage,
)
from app.services.runtime_assistant.redaction import redact_sensitive


class RuntimeAssistantRecords:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def resolve_conversation(
        self,
        *,
        organization_id: uuid.UUID,
        project_id: uuid.UUID,
        runtime_id: uuid.UUID,
        user_id: uuid.UUID,
        conversation_id: str | None,
        title: str | None = None,
        environment: str = "production",
    ) -> RuntimeAssistantConversation:
        conversation = None
        if conversation_id:
            try:
                parsed = uuid.UUID(conversation_id)
            except ValueError:
                raise ValueError("Invalid conversation id") from None
            result = await self.session.execute(
                select(RuntimeAssistantConversation).where(
                    RuntimeAssistantConversation.id == parsed,
                    RuntimeAssistantConversation.organization_id == organization_id,
                    RuntimeAssistantConversation.project_id == project_id,
                    RuntimeAssistantConversation.runtime_id == runtime_id,
                    RuntimeAssistantConversation.user_id == user_id,
                    RuntimeAssistantConversation.status == "active",
                )
            )
            conversation = result.scalar_one_or_none()
            if conversation is None:
                raise ValueError("Conversation not found in this runtime scope")
        if conversation is None:
            conversation = RuntimeAssistantConversation(
                organization_id=organization_id,
                project_id=project_id,
                runtime_id=runtime_id,
                user_id=user_id,
                environment=environment,
                title=(title or "Runtime investigation")[:255],
            )
            self.session.add(conversation)
            await self.session.flush()
        return conversation

    async def add_message(
        self,
        conversation: RuntimeAssistantConversation,
        *,
        role: str,
        content: str,
        mode: str = "observe",
        confidence: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RuntimeAssistantMessage:
        message = RuntimeAssistantMessage(
            conversation_id=conversation.id,
            role=role,
            content=redact_sensitive(content),
            mode=mode,
            confidence=confidence,
            metadata_=redact_sensitive(metadata or {}),
        )
        self.session.add(message)
        await self.session.flush()
        return message

    async def add_evidence(
        self,
        conversation: RuntimeAssistantConversation,
        message: RuntimeAssistantMessage,
        evidence: list[dict[str, Any]],
    ) -> list[RuntimeAssistantEvidence]:
        records: list[RuntimeAssistantEvidence] = []
        for item in evidence:
            record = RuntimeAssistantEvidence(
                conversation_id=conversation.id,
                message_id=message.id,
                evidence_type=item.get("type", "tool_result"),
                source=item.get("source") or item.get("tool") or "runtime",
                reference_id=item.get("reference_id"),
                title=item.get("title") or item.get("tool") or "Runtime evidence",
                summary=item.get("summary"),
                data=redact_sensitive(item.get("data") or {}),
                deep_link=item.get("deep_link"),
                redacted=True,
            )
            self.session.add(record)
            records.append(record)
        await self.session.flush()
        return records

    async def history(
        self,
        runtime_id: uuid.UUID,
        user_id: uuid.UUID,
        limit: int = 50,
        conversation_id: uuid.UUID | None = None,
    ) -> list[RuntimeAssistantMessage]:
        stmt = (
            select(RuntimeAssistantMessage)
            .join(
                RuntimeAssistantConversation,
                RuntimeAssistantConversation.id == RuntimeAssistantMessage.conversation_id,
            )
            .where(
                RuntimeAssistantConversation.runtime_id == runtime_id,
                RuntimeAssistantConversation.user_id == user_id,
                RuntimeAssistantConversation.status == "active",
            )
        )
        if conversation_id is not None:
            stmt = stmt.where(RuntimeAssistantConversation.id == conversation_id)
        result = await self.session.execute(
            stmt.order_by(RuntimeAssistantMessage.created_at.desc()).limit(min(max(limit, 1), 100))
        )
        return list(reversed(result.scalars().all()))

    async def list_conversations(
        self, runtime_id: uuid.UUID, user_id: uuid.UUID, limit: int = 20
    ) -> list[RuntimeAssistantConversation]:
        result = await self.session.execute(
            select(RuntimeAssistantConversation)
            .where(
                RuntimeAssistantConversation.runtime_id == runtime_id,
                RuntimeAssistantConversation.user_id == user_id,
                RuntimeAssistantConversation.status == "active",
            )
            .order_by(RuntimeAssistantConversation.updated_at.desc())
            .limit(min(max(limit, 1), 50))
        )
        return list(result.scalars().all())

    async def clear(
        self, conversation_id: uuid.UUID, runtime_id: uuid.UUID, user_id: uuid.UUID
    ) -> bool:
        result = await self.session.execute(
            select(RuntimeAssistantConversation).where(
                RuntimeAssistantConversation.id == conversation_id,
                RuntimeAssistantConversation.runtime_id == runtime_id,
                RuntimeAssistantConversation.user_id == user_id,
            )
        )
        conversation = result.scalar_one_or_none()
        if conversation is None:
            return False
        await self.session.delete(conversation)
        await self.session.flush()
        return True


def evidence_from_tool_results(tool_results: list[Any]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for result in tool_results:
        call = result.tool_call
        data = redact_sensitive(call.result or {})
        reference_id = _find_reference(data)
        evidence.append(
            {
                "type": _evidence_type(call.name),
                "source": call.name,
                "tool": call.name,
                "title": call.name.replace("_", " ").title(),
                "summary": f"{call.status} in {round(call.duration_ms or 0)} ms",
                "reference_id": reference_id,
                "deep_link": _deep_link(call.name, reference_id),
                "data": data,
                "status": call.status,
                "duration_ms": call.duration_ms,
            }
        )
    return evidence


def _find_reference(data: Any) -> str | None:
    if not isinstance(data, dict):
        return None
    for key in ("trace_id", "request_id", "deployment_id", "runtime_id", "source_id", "tool_id"):
        if data.get(key):
            return str(data[key])
    return None


def _evidence_type(tool: str) -> str:
    for needle, kind in (("log", "logs"), ("analytic", "telemetry"), ("health", "health"), ("deployment", "deployment"), ("knowledge", "source"), ("tool", "tool"), ("security", "security"), ("billing", "usage")):
        if needle in tool:
            return kind
    return "runtime"


def _deep_link(tool: str, reference_id: str | None) -> str | None:
    if "log" in tool:
        return f"/dashboard/analytics?tab=logs{f'&request_id={reference_id}' if reference_id else ''}"
    if "analytic" in tool or "health" in tool:
        return "/dashboard/analytics"
    if "knowledge" in tool:
        return "/dashboard/knowledge"
    if "tool" in tool:
        return "/dashboard/tools"
    return None
