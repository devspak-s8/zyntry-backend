from __future__ import annotations

import uuid
import logging
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from app.core.database import get_session
from app.repositories import UnitOfWork
from app.services.runtime_assistant.context import RuntimeContextBuilder
from app.services.runtime_assistant.diagnostics import RuntimeDiagnostics
from app.services.runtime_assistant.executor import RuntimeAssistantExecutor
from app.services.runtime_assistant.memory import RuntimeAssistantMemory
from app.services.runtime_assistant.optimizer import RuntimeOptimizer
from app.services.runtime_assistant.planner import RuntimeAssistantPlanner
from app.services.runtime_assistant.recommendations import RuntimeRecommendations
from app.services.runtime_assistant.records import RuntimeAssistantRecords, evidence_from_tool_results
from app.services.runtime_assistant.schemas import (
    AssistantMessage,
    AssistantResponse,
    DiagnosticResult,
    OptimizationResult,
    RuntimeContext,
    ToolCall,
    ToolDefinition,
    UserRole,
)

logger = logging.getLogger(__name__)


class RuntimeAssistantService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.uow = UnitOfWork(session)

    async def chat(
        self,
        runtime_id: str,
        user_id: str,
        user_role: str,
        message: str,
        stream: bool = False,
        conversation_id: str | None = None,
    ) -> AssistantResponse | AsyncGenerator[str, None]:
        role = _parse_user_role(user_role)
        context_builder = RuntimeContextBuilder(
            uow=self.uow,
            runtime_id=runtime_id,
            user_id=user_id,
            user_role=role.value,
        )
        context = await context_builder.build()
        records = RuntimeAssistantRecords(self.session)
        conversation = await records.resolve_conversation(
            organization_id=uuid.UUID(context.organization_id),
            project_id=uuid.UUID(context.project_id),
            runtime_id=uuid.UUID(runtime_id),
            user_id=uuid.UUID(user_id),
            conversation_id=conversation_id,
            title=message[:120],
            environment=str(context.runtime.get("environment") or "production"),
        )
        memory = RuntimeAssistantMemory(
            self.uow,
            runtime_id,
            user_id,
            conversation_id=str(conversation.id),
            create_new=False,
        )
        await memory.load()

        await records.add_message(
            conversation, role="user", content=message, mode=_infer_mode(message)
        )

        planner = RuntimeAssistantPlanner(
            context=context,
            available_tools=_get_available_tools(role),
        )
        decision = planner.classify_request(message)
        plan = planner.plan(message)

        executor = RuntimeAssistantExecutor(
            uow=self.uow,
            context=context,
            available_tools=_get_available_tools(role),
        )
        tool_results = await executor.execute_plan(plan.tool_calls)

        for result in tool_results:
            await memory.save_action(result.tool_call.name, result.tool_call.result or {})

        response = executor.build_response(message, tool_results)
        response.context = context
        evidence = evidence_from_tool_results(tool_results)
        response.metadata.update(
            {
                "assistant": "runtime_assistant",
                "mode": _infer_mode(message),
                "evidence": evidence,
                "confidence": _evidence_confidence(tool_results),
                "changes_applied": False,
                "approval_required": any(
                    term in message.lower()
                    for term in ("enable", "disable", "change", "apply", "restart", "delete")
                ),
                "conversation_id": str(conversation.id),
                "decision": decision,
                "plan_reason": plan.reasoning,
            }
        )

        # Persist the answer before optional enrichment so transient optimizer
        # failures never erase an otherwise successful conversation turn.
        assistant_record = await records.add_message(
            conversation,
            role="assistant",
            content=response.message,
            mode=_infer_mode(message),
            confidence=response.metadata["confidence"],
            metadata=response.metadata,
        )
        evidence_records = await records.add_evidence(
            conversation, assistant_record, evidence
        )
        response.metadata["evidence"] = [
            {**item, "id": str(record.id)}
            for item, record in zip(evidence, evidence_records, strict=True)
        ]
        await self.session.commit()

        try:
            recommendations = await RuntimeRecommendations(
                self.uow, runtime_id, user_id
            ).generate()
            response.optimizations.extend(recommendations)
        except Exception:
            logger.exception("Runtime Assistant recommendation enrichment failed")

        logger.info(
            "RuntimeAssistant chat completed",
            extra={
                "runtime_id": runtime_id,
                "user_id": user_id,
                "user_role": role.value,
                "tools_executed": len(tool_results),
                "successful_tools": sum(1 for r in tool_results if r.success),
            },
        )

        if stream:
            return self._stream_response(response)
        return response

    async def get_runtime_summary(self, runtime_id: str, user_id: str) -> dict[str, Any]:
        runtime = await self.uow.runtimes.get(uuid.UUID(runtime_id))
        if not runtime:
            raise ValueError("Runtime not found")
        health = await self.uow.runtime_health_checks.get_latest_by_runtime(uuid.UUID(runtime_id))
        from app.services.billing import BillingService

        billing_service = BillingService(self.uow.session)
        billing_summary = await billing_service.get_usage_summary(
            uuid.UUID(user_id) if user_id else None
        )

        monthly_cost = None
        if billing_summary:
            total_cost = billing_summary.get("total_cost")
            if total_cost is not None and hasattr(total_cost, "__float__"):
                monthly_cost = float(total_cost)

        return {
            "runtime_id": runtime_id,
            "status": runtime.status,
            "health_score": health.health_score if health else runtime.health,
            "provider": runtime.provider,
            "model": runtime.model,
            "embedding_model": runtime.embedding_model,
            "vector_store": runtime.vector_store,
            "documents": runtime.documents,
            "chunks": runtime.chunks,
            "embeddings": runtime.embeddings,
            "last_build_completed": runtime.last_build_completed.isoformat() if runtime.last_build_completed else None,
            "last_propagated": runtime.last_propagated.isoformat() if runtime.last_propagated else None,
            "monthly_cost": monthly_cost,
            "error_count": health.error_count if health else 0,
        }

    async def get_chat_history(
        self,
        runtime_id: str,
        user_id: str,
        limit: int = 20,
        conversation_id: str | None = None,
    ) -> list[AssistantMessage]:
        records = RuntimeAssistantRecords(self.session)
        parsed_conversation = uuid.UUID(conversation_id) if conversation_id else None
        messages = await records.history(
            uuid.UUID(runtime_id), uuid.UUID(user_id), limit, parsed_conversation
        )
        if messages:
            return [
                AssistantMessage(
                    role=item.role,
                    content=item.content,
                    timestamp=item.created_at,
                    metadata={
                        **(item.metadata_ or {}),
                        "conversation_id": str(item.conversation_id),
                        "message_id": str(item.id),
                        "mode": item.mode,
                        "confidence": item.confidence,
                    },
                )
                for item in messages
            ]
        memory = RuntimeAssistantMemory(self.uow, runtime_id, user_id, create_new=False)
        await memory.load()
        return memory.get_chat_history(limit=limit)

    async def get_previous_actions(self, runtime_id: str, limit: int = 10) -> list[dict[str, Any]]:
        memory = RuntimeAssistantMemory(self.uow, runtime_id, "system")
        await memory.load()
        return memory.get_previous_actions(limit=limit)

    async def run_diagnostics(
        self, runtime_id: str, user_id: str, user_role: str
    ) -> list[DiagnosticResult]:
        role = _parse_user_role(user_role)
        diagnostics = RuntimeDiagnostics(self.uow, runtime_id, user_id)
        return await diagnostics.run_full_diagnostics()

    async def get_recommendations(
        self, runtime_id: str, user_id: str
    ) -> list[OptimizationResult]:
        recommendations = RuntimeRecommendations(self.uow, runtime_id, user_id)
        return await recommendations.generate()

    async def _stream_response(self, response: AssistantResponse) -> AsyncGenerator[str, None]:
        yield response.message


def _get_available_tools(user_role: UserRole) -> list[ToolDefinition]:
    from app.services.runtime_assistant.prompts import build_tool_definitions
    from app.services.runtime_assistant.permissions import filter_available_tools

    all_tools = build_tool_definitions()
    allowed = filter_available_tools(user_role, [tool.model_dump() for tool in all_tools])
    allowed_names = {tool["name"] for tool in allowed}
    return [tool for tool in all_tools if tool.name in allowed_names]


def _parse_user_role(user_role: str) -> UserRole:
    try:
        return UserRole(user_role.lower())
    except (ValueError, AttributeError):
        return UserRole.VIEWER


def _infer_mode(message: str) -> str:
    lowered = message.lower()
    if any(term in lowered for term in ("apply", "change", "enable", "disable", "restart")):
        return "configure"
    if any(term in lowered for term in ("simulate", "what if")):
        return "simulate"
    if any(term in lowered for term in ("optimize", "cheaper", "faster", "recommend")):
        return "optimize"
    if any(term in lowered for term in ("why", "failed", "cause", "investigate", "wrong")):
        return "investigate"
    return "observe"


def _evidence_confidence(tool_results: list[Any]) -> float:
    if not tool_results:
        return 0.0
    successful = sum(1 for result in tool_results if result.success)
    return round(successful / len(tool_results), 2)


async def get_runtime_assistant_service(
    session: AsyncSession = Depends(get_session),
) -> RuntimeAssistantService:
    return RuntimeAssistantService(session)
