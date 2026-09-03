from __future__ import annotations

import uuid
import logging
import re
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
from app.services.model_compatibility import provider_model_mismatch

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
        action_proposal_error: str | None = None
        if mutating_calls:
            pending = mutating_calls[0]
            try:
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
            except (ValueError, PermissionError) as exc:
                # A malformed or incompatible change should become an
                # assistant explanation, not a 500 from the chat endpoint.
                action_proposal_error = str(exc)

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
        # Configuration and routing answers are control-plane facts. The LLM
        # may phrase ordinary conversation naturally, but it must not replace
        # a verified saved value with an inferred or stale statement.
        verified_configuration = _verified_configuration_message(message, tool_results)
        if verified_configuration:
            response.message = verified_configuration
        verified_completion = _verified_completion_message(message, tool_results)
        if verified_completion:
            response.message = verified_completion
        context_factual = _context_factual_message(message, context)
        if context_factual and not action_proposal:
            # These values are loaded with the scoped control-plane snapshot,
            # so a provider outage or an unavailable optional tool cannot make
            # the assistant fall back to stale model-generated facts.
            response.message = context_factual
        if action_proposal and _is_generic_runtime_help(response.message):
            response.message = (
                f"I can prepare this change for the {context.runtime.get('name') or 'runtime'}. "
                "Review the proposed operation below; nothing is applied until you approve it."
            )
        if action_proposal_error:
            response.message = (
                f"I could not prepare that runtime change: {action_proposal_error} "
                "No changes were applied."
            )
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
                "action_proposal_error": action_proposal_error,
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


def _verified_configuration_message(
    user_message: str,
    tool_results: list[Any],
) -> str | None:
    """Build a concise configuration answer from the latest tool result.

    The assistant's language model can occasionally confuse the base routing
    strategy with the dynamic-routing flag. For configuration questions, use
    the freshly-read control-plane value so the answer cannot contradict the
    saved runtime state.
    """
    lowered = user_message.lower()
    if not any(
        term in lowered
        for term in (
            "configuration", "configured", "settings", "routing", "route",
            "provider", "model", "temperature", "dynamic",
        )
    ):
        return None
    config_result = next(
        (
            result.tool_call.result
            for result in tool_results
            if result.success
            and result.tool_call.name == "get_runtime_config"
            and isinstance(result.tool_call.result, dict)
        ),
        None,
    )
    if not config_result:
        return None
    config = config_result.get("config") or {}
    dynamic_enabled = bool(config.get("dynamic_routing_enabled"))
    dynamic_state = "enabled" if dynamic_enabled else "disabled"
    base_strategy = config_result.get("routing_strategy") or "not set"
    provider = config_result.get("provider") or "automatic"
    model = config_result.get("model") or "automatic"
    mismatch = provider_model_mismatch(provider, model)
    asks_for_strategies = (
        ("available" in lowered or "list" in lowered or "which" in lowered)
        and "strateg" in lowered
    )
    explains_dynamic = (
        ("how" in lowered or "explain" in lowered or "work" in lowered)
        and any(term in lowered for term in ("automatic", "dynamic", "routing", "route"))
    )
    if asks_for_strategies:
        return (
            "Available routing strategies:\n"
            "- `latency_optimized` — prioritize lower response latency.\n"
            "- `balanced` — trade off quality, latency, and cost.\n"
            "- `quality_optimized` — prioritize answer quality.\n\n"
            "Automatic model routing is separate from this list. Enable dynamic "
            "model routing to let Zyntry choose a connected model for each request; "
            "the selected strategy becomes its preference."
        )
    if explains_dynamic:
        return (
            f"Dynamic model routing is **{dynamic_state}** for this runtime. "
            f"The current preference is `{base_strategy}`. When enabled, Zyntry "
            "evaluates the request, available provider credentials, latency, cost, "
            "and this preference before choosing a connected model. When disabled, "
            "requests stay on the configured provider and model, plus explicit "
            "fallbacks."
        )
    if "routing" in lowered or "route" in lowered or "dynamic" in lowered:
        message = (
            f"The saved runtime configuration has dynamic model routing **{dynamic_state}**. "
            f"The base routing strategy is `{base_strategy}`, with `{model}` as the configured model "
            f"for provider `{provider}`. The base strategy remains unchanged because automatic model "
            "selection is controlled by the dynamic-routing setting."
        )
        return f"{message}\n\nWarning: {mismatch}" if mismatch else message
    message = (
        "Current saved runtime configuration:\n"
        f"- Provider: `{provider}`\n"
        f"- Model: `{model}`\n"
        f"- Base routing strategy: `{base_strategy}`\n"
        f"- Dynamic model routing: **{dynamic_state}**\n"
        f"- Environment: `{config_result.get('environment') or 'not set'}`\n"
        f"- Embedding model: `{config_result.get('embedding_model') or 'default'}`\n"
        f"- Vector store: `{config_result.get('vector_store') or 'default'}`"
    )
    return f"{message}\n- Warning: {mismatch}" if mismatch else message


def _is_generic_runtime_help(message: str) -> bool:
    normalized = " ".join((message or "").lower().split())
    return normalized in {
        "i’m here to help with this runtime. ask me about its status, configuration, integrations, knowledge sources, performance, costs, or recent failures.",
        "i'm here to help with this runtime. ask me about its status, configuration, integrations, knowledge sources, performance, costs, or recent failures.",
    }


def _context_factual_message(user_message: str, context: RuntimeContext) -> str | None:
    """Answer common read questions from the fresh runtime snapshot.

    The responder is still used for natural language, but these control-plane
    facts must remain correct even when an LLM call is unavailable or stale.
    Multiple sections are returned when a user asks several questions in one
    message.
    """

    lowered = user_message.lower()
    sections: list[str] = []
    is_mutation = any(term in lowered for term in (
        "change", "switch", "set ", "enable", "disable", "update", "configure",
    ))
    asks_provider_model = (
        not is_mutation
        and "provider" in lowered
        and "model" in lowered
        and any(term in lowered for term in ("what", "which", "using", "configured"))
    )
    if asks_provider_model:
        provider = context.runtime.get("provider") or "automatic"
        model = context.runtime.get("model") or "automatic"
        mismatch = provider_model_mismatch(provider, model)
        section = f"Current provider and model: `{provider}` / `{model}`."
        if mismatch:
            section += f"\nWarning: {mismatch}"
        sections.append(section)

    if "integration" in lowered or "connected connector" in lowered:
        integrations = context.integrations
        if integrations:
            lines = ["Runtime integrations:"]
            for item in integrations:
                slug = str(item.get("integration_slug") or "integration").replace("_", " ")
                status = str(item.get("connection_status") or item.get("status") or "not configured").replace("_", " ")
                lines.append(f"- {slug}: {status}")
            sections.append("\n".join(lines))
        else:
            sections.append("No integrations are configured for this runtime.")

    if any(term in lowered for term in ("knowledge source", "knowledge available", "uploaded document", "document source")):
        sources = context.knowledge_sources
        if sources:
            lines = ["Knowledge sources:"]
            for source in sources:
                name = source.get("name") or source.get("source_type") or source.get("provider") or "source"
                status = str(source.get("status") or "unknown").replace("_", " ")
                lines.append(f"- {name}: {status}")
            sections.append("\n".join(lines))
        else:
            sections.append("No knowledge sources are currently available for this runtime.")

    if any(term in lowered for term in ("security polic", "security setting", "prompt injection", "pii redaction")):
        policy = context.runtime.get("security_policies") or {}
        keys_count = context.security.get("api_keys_count", 0)
        tracked = (
            "enabled", "block_suspicious_requests", "ip_ban_enabled",
            "prompt_injection_protection", "pii_redaction", "max_input_chars",
            "rate_limit_per_minute", "violation_threshold", "ban_duration_seconds",
        )
        lines = ["Active runtime security policy:"]
        for key in tracked:
            if key in policy:
                lines.append(f"- {key.replace('_', ' ').capitalize()}: {policy[key]}")
        lines.append(f"- API keys visible in this scope: {keys_count}")
        sections.append("\n".join(lines))

    if any(term in lowered for term in ("health", "p95 latency", "latency")):
        health = context.health or {}
        score = health.get("health_score", health.get("health", context.runtime.get("health", "unknown")))
        errors = health.get("error_count", health.get("errors", "unknown"))
        latency = health.get("llm_latency_ms") or health.get("retrieval_latency_ms")
        section = f"Runtime health: `{score}`; errors: `{errors}`."
        if latency is not None:
            section += f" Observed latency: `{latency} ms`."
        sections.append(section)

    if any(term in lowered for term in ("deployment status", "latest deployment", "build status", "waiting for connections", "failing to build")):
        deployment = context.deployment or {}
        status = deployment.get("status") or context.runtime.get("status") or "unknown"
        section = f"Latest deployment status: `{status}`."
        if deployment.get("error_message"):
            section += f" Note: {deployment['error_message']}"
        sections.append(section)

    return "\n\n".join(sections) if sections else None


def _verified_completion_message(
    user_message: str,
    tool_results: list[Any],
) -> str | None:
    """Answer completion checks from the latest control-plane snapshot.

    A responder must not claim that it is still applying a change (or that it
    will notify the user later) when the only reliable evidence is the saved
    runtime state. This also gives short follow-ups such as ``do?`` a useful,
    deterministic answer.
    """
    lowered = user_message.strip().lower()
    if not (
        re.fullmatch(r"(?:do|did|done|check|status)\s*[?!.]*", lowered)
        or any(term in lowered for term in (
            "are you done", "is it done", "did it apply", "was it applied",
            "has it completed", "when completed", "is it live", "did the update",
            "did the change", "was the change", "verify the change",
        ))
    ):
        return None
    config_result = next(
        (
            result.tool_call.result
            for result in tool_results
            if result.success
            and result.tool_call.name == "get_runtime_config"
            and isinstance(result.tool_call.result, dict)
        ),
        None,
    )
    deployment_result = next(
        (
            result.tool_call.result
            for result in tool_results
            if result.success
            and result.tool_call.name == "get_deployment_status"
            and isinstance(result.tool_call.result, dict)
        ),
        None,
    )
    if not config_result and not deployment_result:
        return None
    config_result = config_result or {}
    deployment_result = deployment_result or {}
    runtime_status = deployment_result.get("status") or config_result.get("status") or "unknown"
    dynamic_state = "enabled" if (config_result.get("config") or {}).get("dynamic_routing_enabled") else "disabled"
    note = deployment_result.get("error_message")
    message = (
        f"I checked the backend. The runtime is `{runtime_status}` and the saved "
        f"dynamic model routing setting is **{dynamic_state}**. "
        "This is the latest verified state; no unconfirmed change was applied by this check."
    )
    if deployment_result.get("last_propagated"):
        message += f" Last propagated: `{deployment_result['last_propagated']}`."
    if note:
        message += f" Backend note: {note}"
    return message


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
