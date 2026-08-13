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
    ) -> AssistantResponse | AsyncGenerator[str, None]:
        role = _parse_user_role(user_role)
        context_builder = RuntimeContextBuilder(
            uow=self.uow,
            runtime_id=runtime_id,
            user_id=user_id,
            user_role=role.value,
        )
        context = await context_builder.build()
        memory = RuntimeAssistantMemory(self.uow, runtime_id)
        await memory.load()

        await memory.save_chat_message("user", message)

        planner = RuntimeAssistantPlanner(
            context=context,
            available_tools=_get_available_tools(role),
        )
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

        recommendations = await RuntimeRecommendations(
            self.uow, runtime_id, user_id
        ).generate()
        response.optimizations.extend(recommendations)

        await memory.save_chat_message("assistant", response.message)

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

    async def get_chat_history(self, runtime_id: str, limit: int = 20) -> list[AssistantMessage]:
        memory = RuntimeAssistantMemory(self.uow, runtime_id)
        await memory.load()
        return memory.get_chat_history(limit=limit)

    async def get_previous_actions(self, runtime_id: str, limit: int = 10) -> list[dict[str, Any]]:
        memory = RuntimeAssistantMemory(self.uow, runtime_id)
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


async def get_runtime_assistant_service(
    session: AsyncSession = Depends(get_session),
) -> RuntimeAssistantService:
    return RuntimeAssistantService(session)
