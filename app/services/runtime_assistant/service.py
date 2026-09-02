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
from app.services.runtime_assistant.configuration import configuration_change_impact
from app.services.runtime_assistant.commands import RuntimeAssistantCommandService
from app.services.runtime_assistant.diagnostics import RuntimeDiagnostics
from app.services.runtime_assistant.executor import RuntimeAssistantExecutor
from app.services.runtime_assistant.memory import RuntimeAssistantMemory
from app.services.runtime_assistant.optimizer import RuntimeOptimizer
from app.services.runtime_assistant.planner import RuntimeAssistantPlanner
from app.services.runtime_assistant.recommendations import RuntimeRecommendations
from app.services.runtime_assistant.records import RuntimeAssistantRecords, evidence_from_tool_results
from app.services.runtime_assistant.responder import RuntimeAssistantResponder
from app.services.runtime_assistant.schemas import (
    AssistantMessage,
    AssistantResponse,
    ActionType,
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

        available_tools = _get_available_tools(role)
        planner = RuntimeAssistantPlanner(
            context=context,
            available_tools=available_tools,
        )
        decision = planner.classify_request(message)
        plan = planner.plan(message)

        tool_types = {tool.name: tool.action_type for tool in available_tools}
        mutating_calls = [
            call for call in plan.tool_calls
            if tool_types.get(call.name, ActionType.READ) != ActionType.READ
        ]
        executable_calls = [call for call in plan.tool_calls if call not in mutating_calls]

        executor = RuntimeAssistantExecutor(
            uow=self.uow,
            context=context,
            available_tools=available_tools,
        )
        tool_results = await executor.execute_plan(executable_calls)

        action_proposal: dict[str, Any] | None = None
        if mutating_calls:
            pending = mutating_calls[0]
            proposal = await RuntimeAssistantCommandService(self.uow).propose(
                runtime_id=uuid.UUID(runtime_id),
                project_id=uuid.UUID(context.project_id),
                user_id=uuid.UUID(user_id),
                user_role=role,
                action=pending.name,
                arguments=pending.arguments,
            )
            action_proposal = {
                "id": str(proposal.id),
                "action": proposal.action,
                "arguments": proposal.arguments,
                "risk": proposal.risk,
                "expires_at": proposal.expires_at.isoformat(),
                "status": proposal.status,
                "requires_confirmation": True,
            }

        for result in tool_results:
            await memory.save_action(result.tool_call.name, result.tool_call.result or {})

        response = executor.build_response(message, tool_results)
        response.context = context
        evidence = evidence_from_tool_results(tool_results)
        conversation_history = await records.history(
            uuid.UUID(runtime_id), uuid.UUID(user_id), 10, conversation.id
        )
        generated_message = await RuntimeAssistantResponder().generate(
            user_message=message,
            context=context,
            decision=decision,
            tool_evidence=evidence,
            recent_messages=[
                {"role": item.role, "content": item.content}
                for item in conversation_history
            ],
            pending_action=action_proposal,
        )
        if generated_message:
            response.message = generated_message
        if plan.configuration_error:
            response.message = (
                f"{response.message}\n\n"
                f"I could not prepare that configuration change: {plan.configuration_error} "
                "No changes were applied."
            ).strip()
        control_plane_diagnostics = _diagnose_control_plane_state(context)
        if control_plane_diagnostics and tool_results:
            response.diagnostics = [*control_plane_diagnostics, *response.diagnostics]
            response.message = (
                _format_control_plane_diagnostics(control_plane_diagnostics, context)
                + (f"\n\n{response.message}" if response.message else "")
            )
        evidence.insert(0, {
            "source": "control_plane_snapshot",
            "reference_id": runtime_id,
            "observed_at": context.observed_at.isoformat() if context.observed_at else None,
            "data": {
                "deployment": context.deployment,
                "snapshot_sources": context.snapshot_sources,
            },
        })
        response.metadata.update(
            {
                "assistant": "runtime_assistant",
                "mode": _infer_mode(message),
                "evidence": evidence,
                "confidence": _evidence_confidence(tool_results),
                "changes_applied": False,
                "approval_required": action_proposal is not None,
                "action_proposal": action_proposal,
                "conversation_id": str(conversation.id),
                "decision": decision,
                "plan_reason": plan.reasoning,
                "configuration_error": plan.configuration_error,
            }
        )
        if action_proposal:
            if action_proposal["action"] == "update_runtime_configuration":
                changes = action_proposal.get("arguments", {}).get("changes", {})
                impact = configuration_change_impact(changes)
                action_proposal["impact"] = impact
                change_lines = [
                    f"- {field.replace('_', ' ').replace('.', ': ')}: "
                    f"{_current_configuration_value(context, field)} -> {value}"
                    for field, value in _flatten_configuration_changes(changes)
                ]
                response.message = (
                    f"{response.message}\n\nProposed configuration change:\n"
                    + "\n".join(change_lines)
                )
                if impact["requires_rebuild"]:
                    response.message += (
                        "\n\nThis change affects the runtime artifact or retrieval index. "
                        "After approval, a separate rebuild may be required before it is fully live."
                    )
            response.message = (
                f"{response.message}\n\n"
                f"The backend requires confirmation before {action_proposal['action'].replace('_', ' ')}."
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


def _flatten_configuration_changes(changes: dict[str, Any]) -> list[tuple[str, Any]]:
    flattened: list[tuple[str, Any]] = []
    for key, value in changes.items():
        if key == "config" and isinstance(value, dict):
            flattened.extend((f"config.{nested}", nested_value) for nested, nested_value in value.items())
        else:
            flattened.append((key, value))
    return flattened


def _current_configuration_value(context: RuntimeContext, field: str) -> Any:
    if field.startswith("config."):
        value = context.config.get(field.removeprefix("config."))
    else:
        value = context.runtime.get(field)
    return "(not set)" if value is None else value


def _evidence_confidence(tool_results: list[Any]) -> float:
    if not tool_results:
        return 0.0
    successful = sum(1 for result in tool_results if result.success)
    return round(successful / len(tool_results), 2)


async def get_runtime_assistant_service(
    session: AsyncSession = Depends(get_session),
) -> RuntimeAssistantService:
    return RuntimeAssistantService(session)


def _diagnose_control_plane_state(context: RuntimeContext) -> list[DiagnosticResult]:
    status = str(context.deployment.get("observed_status") or context.runtime.get("status") or "unknown").lower()
    diagnostics: list[DiagnosticResult] = []
    required_connections = [
        item.get("integration_slug", "integration")
        for item in context.integrations
        if item.get("is_enabled")
        and item.get("connection_required")
        and item.get("connection_status") != "connected"
    ]

    if status == "awaiting_connections":
        names = ", ".join(required_connections) if required_connections else "one or more required integrations"
        diagnostics.append(DiagnosticResult(
            issue="Runtime is waiting for connections",
            severity="warning",
            description=f"Provisioning cannot continue until {names} are connected.",
            affected_components=["runtime", "integrations"],
            recommendations=["Connect the required integration credentials, then rebuild the runtime."],
            metrics={"observed_status": status, "required_connections": required_connections},
        ))
    elif status == "awaiting_documents":
        diagnostics.append(DiagnosticResult(
            issue="Runtime is waiting for documents",
            severity="warning",
            description="Provisioning cannot continue because its required document collection is empty.",
            affected_components=["runtime", "knowledge"],
            recommendations=["Upload or connect at least one required document source, then rebuild the runtime."],
            metrics={"observed_status": status, "documents": context.runtime.get("documents", 0)},
        ))
    elif status in {"preconfigured", "queued", "validating", "discovering", "extracting", "cleaning", "chunking", "embedding", "indexing", "building", "provisioning"}:
        diagnostics.append(DiagnosticResult(
            issue="Runtime is not active yet",
            severity="info",
            description=f"The control plane reports the runtime in the {status} stage.",
            affected_components=["runtime", "deployment"],
            recommendations=["Wait for the current stage to finish or inspect the latest build log if progress has stopped."],
            metrics={"observed_status": status, "desired_status": context.deployment.get("desired_status")},
        ))
    elif status in {"failed", "cancelled", "inactive", "paused", "stopped"}:
        reason = context.deployment.get("error_message") or f"The runtime is currently {status}."
        diagnostics.append(DiagnosticResult(
            issue="Runtime is not running",
            severity="error" if status == "failed" else "warning",
            description=str(reason),
            affected_components=["runtime", "deployment"],
            recommendations=["Review the latest build and error evidence before proposing a restart or rebuild."],
            metrics={"observed_status": status, "desired_status": context.deployment.get("desired_status")},
        ))

    unavailable = sorted(
        name for name, state in context.snapshot_sources.items()
        if state.get("status") == "unavailable"
    )
    if unavailable:
        diagnostics.append(DiagnosticResult(
            issue="Some control-plane evidence is unavailable",
            severity="info",
            description=f"The assistant could not read: {', '.join(unavailable)}. Other evidence was still evaluated.",
            affected_components=unavailable,
            recommendations=["Retry the investigation if one of these sources is required for a conclusive answer."],
            metrics={"unavailable_sources": unavailable},
        ))
    return diagnostics


def _format_control_plane_diagnostics(
    diagnostics: list[DiagnosticResult], context: RuntimeContext
) -> str:
    observed_at = context.observed_at.isoformat() if context.observed_at else "the latest snapshot"
    lines = [f"Control-plane diagnosis (observed {observed_at}):"]
    for diagnostic in diagnostics:
        lines.append(f"- {diagnostic.issue}: {diagnostic.description}")
    lines.append("This diagnosis does not require the runtime process itself to be running.")
    return "\n".join(lines)
