from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from app.repositories import UnitOfWork
from app.services.health import HealthService
from app.services.knowledge import KnowledgeService
from app.services.providers import ProviderService
from app.services.runtimes import RuntimeService
from app.services.tools import ToolService
from app.services.runtime_assistant.permissions import PermissionDeniedError, check_tool_permission
from app.services.runtime_assistant.configuration import (
    configuration_change_impact,
    normalize_configuration_changes,
)
from app.services.runtime_assistant.schemas import (
    ActionType,
    ToolCall,
    ToolDefinition,
    UserRole,
)


class RuntimeAssistantTools:
    def __init__(
        self,
        uow: UnitOfWork,
        runtime_id: str,
        user_id: str,
        user_role: UserRole,
        project_id: str | None = None,
    ) -> None:
        self.uow = uow
        self.runtime_id = runtime_id
        self.user_id = user_id
        self.user_role = user_role
        self.project_id = project_id
        self.runtime_service = RuntimeService(uow)
        self.provider_service = ProviderService(uow)
        self.knowledge_service = KnowledgeService(uow)
        self.tool_service = ToolService(uow)
        self.health_service = HealthService(uow)

    def get_available_tools(self) -> list[ToolDefinition]:
        all_tools = _ALL_TOOLS
        available = []
        for tool_def in all_tools:
            check = check_tool_permission(
                self.user_role,
                tool_def.name,
                [t.model_dump() for t in all_tools],
            )
            if check.allowed:
                available.append(tool_def)
        return available

    async def execute(self, tool_call: ToolCall) -> ToolCall:
        tool_name = tool_call.name
        arguments = tool_call.arguments or {}

        tool_map = _TOOL_MAP
        handler = tool_map.get(tool_name)
        if not handler:
            tool_call.status = "error"
            tool_call.error = f"Unknown tool: {tool_name}"
            tool_call.timestamp = datetime.now(timezone.utc)
            return tool_call

        start = datetime.now(timezone.utc)
        try:
            result = await handler(self, **arguments)
            tool_call.status = "success"
            tool_call.result = result
        except PermissionDeniedError as exc:
            tool_call.status = "permission_denied"
            tool_call.error = str(exc)
        except ValueError as exc:
            tool_call.status = "error"
            tool_call.error = str(exc)
        except Exception as exc:
            tool_call.status = "error"
            tool_call.error = f"Tool execution failed: {exc}"
        finally:
            end = datetime.now(timezone.utc)
            tool_call.duration_ms = (end - start).total_seconds() * 1000
            tool_call.timestamp = start

        return tool_call


async def _get_runtime_summary(self: RuntimeAssistantTools) -> dict[str, Any]:
    runtime = await self.runtime_service.get(self.runtime_id)
    if not runtime:
        raise ValueError("Runtime not found")

    health = await self.health_service.get_runtime_health(self.runtime_id)
    project_id = runtime.get("project_id", "")

    knowledge_sources = await self.knowledge_service.list_sources(project_id)
    tools = await self.tool_service.list_tools(project_id)

    from app.services.billing import BillingService

    billing_service = BillingService(self.uow.session)
    billing_summary = await billing_service.get_usage_summary(
        uuid.UUID(self.user_id) if self.user_id else None
    )

    failed_sources = [
        s for s in knowledge_sources if s.get("status") in ("error", "failed")
    ]

    issues = []
    if runtime.get("status") != "active":
        issues.append(f"Runtime status is {runtime.get('status')}")
    if health.get("health_score", 100) < 70:
        issues.append(f"Health score is low: {health.get('health_score')}")
    if failed_sources:
        issues.append(f"{len(failed_sources)} knowledge source(s) have failed")
    if health.get("error_count", 0) > 0:
        issues.append(f"{health.get('error_count')} recent errors detected")

    monthly_cost = None
    if billing_summary:
        total_cost = billing_summary.get("total_cost")
        if total_cost is not None and hasattr(total_cost, "__float__"):
            monthly_cost = float(total_cost)

    return {
        "runtime_id": self.runtime_id,
        "status": runtime.get("status", "unknown"),
        "health_score": health.get("health_score"),
        "provider": runtime.get("provider", "unknown"),
        "model": runtime.get("model", "unknown"),
        "embedding_model": runtime.get("embedding_model", "unknown"),
        "vector_store": runtime.get("vector_store", "unknown"),
        "documents": runtime.get("documents", 0),
        "chunks": runtime.get("chunks", 0),
        "embeddings": runtime.get("embeddings", 0),
        "knowledge_sources_count": len(knowledge_sources),
        "tools_count": len(tools),
        "last_build_completed": runtime.get("last_build_completed"),
        "last_propagated": runtime.get("last_propagated"),
        "monthly_cost": monthly_cost,
        "error_count": health.get("error_count", 0),
        "issues": issues,
    }


async def _get_runtime_health(self: RuntimeAssistantTools) -> dict[str, Any]:
    return await self.health_service.get_runtime_health(self.runtime_id)


async def _get_runtime_config(self: RuntimeAssistantTools) -> dict[str, Any]:
    runtime = await self.runtime_service.get(self.runtime_id)
    if not runtime:
        raise ValueError("Runtime not found")
    return {
        "name": runtime.get("name"),
        "status": runtime.get("status"),
        "environment": runtime.get("environment"),
        "provider": runtime.get("provider"),
        "model": runtime.get("model"),
        "routing_strategy": runtime.get("routing_strategy"),
        "embedding_model": runtime.get("embedding_model"),
        "vector_store": runtime.get("vector_store"),
        "chunk_size": runtime.get("chunk_size"),
        "chunk_overlap": runtime.get("chunk_overlap"),
        "config": runtime.get("config", {}),
        "security_policies": runtime.get("security_policies", {}),
        "metadata": runtime.get("metadata_", {}),
    }


async def _get_providers(self: RuntimeAssistantTools) -> list[dict[str, Any]]:
    runtime = await self.runtime_service.get(self.runtime_id)
    if not runtime:
        raise ValueError("Runtime not found")
    return await self.provider_service.list_providers(runtime.get("project_id"))


async def _get_models(self: RuntimeAssistantTools) -> list[dict[str, Any]]:
    providers = await _get_providers(self)
    return [
        {
            "provider": p.get("provider_name"),
            "display_name": p.get("display_name"),
            "status": p.get("status"),
            "is_active": p.get("is_active"),
        }
        for p in providers
    ]


async def _get_knowledge_sources(self: RuntimeAssistantTools) -> list[dict[str, Any]]:
    runtime = await self.runtime_service.get(self.runtime_id)
    if not runtime:
        raise ValueError("Runtime not found")
    return await self.knowledge_service.list_sources(runtime.get("project_id"))


async def _get_tools(self: RuntimeAssistantTools) -> list[dict[str, Any]]:
    runtime = await self.runtime_service.get(self.runtime_id)
    if not runtime:
        raise ValueError("Runtime not found")
    return await self.tool_service.list_tools(runtime.get("project_id"))


async def _get_logs(self: RuntimeAssistantTools, limit: int = 50) -> list[dict[str, Any]]:
    from app.repositories.request_logs import RequestLogRepository

    runtime = await self.runtime_service.get(self.runtime_id)
    if not runtime:
        raise ValueError("Runtime not found")

    project_id = runtime.get("project_id", "")
    repo = RequestLogRepository(self.uow.session)
    logs = await repo.list(limit=limit, offset=0)
    project_logs = [log for log in logs if str(log.project_id) == str(project_id)]
    return [
        {
            "id": str(log.id),
            "method": log.method,
            "endpoint": log.endpoint,
            "status": log.status,
            "latency_ms": log.latency_ms,
            "tokens": log.tokens,
            "provider": log.provider,
            "model": log.model,
            "cost": log.cost,
            "started_at": log.started_at,
            "completed_at": log.completed_at,
        }
        for log in project_logs
    ]


async def _get_analytics(self: RuntimeAssistantTools) -> dict[str, Any]:
    runtime = await self.runtime_service.get(self.runtime_id)
    if not runtime:
        raise ValueError("Runtime not found")
    from app.services.analytics import AnalyticsService

    analytics_service = AnalyticsService(self.uow)
    return await analytics_service.get_summary(runtime.get("project_id"))


async def _get_billing(self: RuntimeAssistantTools) -> dict[str, Any]:
    from app.services.billing import BillingService

    billing_service = BillingService(self.uow.session)
    return await billing_service.get_usage_summary(
        uuid.UUID(self.user_id) if self.user_id else None
    )


async def _get_security_settings(self: RuntimeAssistantTools) -> dict[str, Any]:
    from app.services.apikeys import ApiKeyService

    api_key_service = ApiKeyService(self.uow)
    keys = await api_key_service.list_keys()
    return {
        "api_keys_count": len(keys),
        "keys": [
            {
                "id": str(k.id),
                "name": k.name,
                "prefix": k.key_prefix,
                "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
                "expires_at": k.expires_at.isoformat() if k.expires_at else None,
                "revoked": k.revoked,
            }
            for k in keys
        ],
    }


async def _get_deployment_status(self: RuntimeAssistantTools) -> dict[str, Any]:
    runtime = await self.runtime_service.get(self.runtime_id)
    if not runtime:
        raise ValueError("Runtime not found")
    return {
        "status": runtime.get("status"),
        "version": runtime.get("version"),
        "last_build_completed": runtime.get("last_build_completed"),
        "last_propagated": runtime.get("last_propagated"),
        "health": runtime.get("health"),
        "error_message": runtime.get("error_message"),
    }


async def _get_change_history(
    self: RuntimeAssistantTools, limit: int = 20
) -> dict[str, Any]:
    from sqlalchemy import select
    from app.models.actions import ActionAuditLog
    from app.models.runtimes import RuntimeBuildLog

    runtime = await self.uow.runtimes.get(uuid.UUID(self.runtime_id))
    if not runtime:
        raise ValueError("Runtime not found")
    actions_result = await self.uow.session.execute(
        select(ActionAuditLog)
        .where(ActionAuditLog.project_id == runtime.project_id)
        .order_by(ActionAuditLog.created_at.desc())
        .limit(limit)
    )
    builds_result = await self.uow.session.execute(
        select(RuntimeBuildLog)
        .where(RuntimeBuildLog.runtime_id == runtime.id)
        .order_by(RuntimeBuildLog.created_at.desc())
        .limit(limit)
    )
    actions = [
        {
            "action": item.action,
            "status": item.status,
            "arguments": item.arguments or {},
            "result": item.result,
            "user_id": str(item.user_id),
            "created_at": item.created_at.isoformat(),
        }
        for item in actions_result.scalars().all()
    ]
    builds = [
        {
            "stage": item.stage,
            "status": item.status,
            "started_at": item.started_at.isoformat(),
            "completed_at": item.completed_at.isoformat() if item.completed_at else None,
            "metadata": item.metadata_ or {},
        }
        for item in builds_result.scalars().all()
    ]
    return {"actions": actions, "deployments": builds}


async def _enable_dynamic_routing(self: RuntimeAssistantTools) -> dict[str, Any]:
    from app.schemas.runtimes import RuntimeUpdate

    runtime = await self.runtime_service.get(self.runtime_id)
    if not runtime:
        raise ValueError("Runtime not found")
    config = runtime.get("config", {})
    config["dynamic_routing_enabled"] = True
    update_data = RuntimeUpdate(config=config)
    updated = await self.runtime_service.update(self.runtime_id, update_data)
    await self.uow.commit()
    return {"status": "success", "dynamic_routing_enabled": True, "runtime": updated}


async def _disable_dynamic_routing(self: RuntimeAssistantTools) -> dict[str, Any]:
    from app.schemas.runtimes import RuntimeUpdate

    runtime = await self.runtime_service.get(self.runtime_id)
    if not runtime:
        raise ValueError("Runtime not found")
    config = runtime.get("config", {})
    config["dynamic_routing_enabled"] = False
    update_data = RuntimeUpdate(config=config)
    updated = await self.runtime_service.update(self.runtime_id, update_data)
    await self.uow.commit()
    return {"status": "success", "dynamic_routing_enabled": False, "runtime": updated}


async def _change_default_provider(self: RuntimeAssistantTools, provider: str) -> dict[str, Any]:
    from app.schemas.runtimes import RuntimeUpdate

    runtime = await self.runtime_service.get(self.runtime_id)
    if not runtime:
        raise ValueError("Runtime not found")
    update_data = RuntimeUpdate(provider=provider)
    updated = await self.runtime_service.update(self.runtime_id, update_data)
    await self.uow.commit()
    return {"status": "success", "provider": provider, "runtime": updated}


async def _change_temperature(self: RuntimeAssistantTools, temperature: float) -> dict[str, Any]:
    from app.schemas.runtimes import RuntimeUpdate

    runtime = await self.runtime_service.get(self.runtime_id)
    if not runtime:
        raise ValueError("Runtime not found")
    config = runtime.get("config", {})
    config["temperature"] = temperature
    update_data = RuntimeUpdate(config=config)
    updated = await self.runtime_service.update(self.runtime_id, update_data)
    await self.uow.commit()
    return {"status": "success", "temperature": temperature, "runtime": updated}


async def _change_max_tokens(self: RuntimeAssistantTools, max_tokens: int) -> dict[str, Any]:
    from app.schemas.runtimes import RuntimeUpdate

    runtime = await self.runtime_service.get(self.runtime_id)
    if not runtime:
        raise ValueError("Runtime not found")
    config = runtime.get("config", {})
    config["max_tokens"] = max_tokens
    update_data = RuntimeUpdate(config=config)
    updated = await self.runtime_service.update(self.runtime_id, update_data)
    await self.uow.commit()
    return {"status": "success", "max_tokens": max_tokens, "runtime": updated}


async def _update_runtime_configuration(
    self: RuntimeAssistantTools, changes: dict[str, Any]
) -> dict[str, Any]:
    """Apply a confirmed, allowlisted RuntimeUpdate payload.

    This is intentionally separate from the generic PATCH endpoint so the
    assistant cannot change runtime ownership, lifecycle status, or secrets.
    """
    from app.schemas.runtimes import RuntimeUpdate

    runtime = await self.runtime_service.get(self.runtime_id)
    if not runtime:
        raise ValueError("Runtime not found")

    normalized = normalize_configuration_changes(changes)
    current_config = dict(runtime.get("config") or {})
    config_updates = normalized.pop("config", None)
    if config_updates:
        current_config.update(config_updates)
        normalized["config"] = current_config

    effective_chunk_size = normalized.get("chunk_size", runtime.get("chunk_size", 512))
    effective_chunk_overlap = normalized.get("chunk_overlap", runtime.get("chunk_overlap", 64))
    if effective_chunk_overlap >= effective_chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")

    update_data = RuntimeUpdate(**normalized)
    updated = await self.runtime_service.update(self.runtime_id, update_data)
    impact = configuration_change_impact(
        {**normalized, "config": config_updates} if config_updates else normalized
    )
    return {
        "status": "success",
        **impact,
        "runtime": updated,
    }


async def _sync_sources(self: RuntimeAssistantTools) -> dict[str, Any]:
    runtime = await self.runtime_service.get(self.runtime_id)
    if not runtime:
        raise ValueError("Runtime not found")
    project_id = runtime.get("project_id", "")
    sources = await self.knowledge_service.list_sources(project_id)
    results = []
    for source in sources:
        try:
            result = await self.knowledge_service.sync_source(str(source.get("id", "")))
            results.append({"source_id": str(source.get("id")), "status": "queued", "result": result})
        except Exception as exc:
            results.append(
                {"source_id": str(source.get("id")), "status": "error", "error": str(exc)}
            )
    return {"status": "completed", "synced": len(results), "results": results}


async def _rebuild_embeddings(self: RuntimeAssistantTools) -> dict[str, Any]:
    from app.tasks.runtimes import build_runtime_task

    build_runtime_task.delay(self.runtime_id, trigger="assistant_rebuild")
    return {"status": "queued", "runtime_id": self.runtime_id, "action": "rebuild_embeddings"}


async def _clear_cache(self: RuntimeAssistantTools) -> dict[str, Any]:
    try:
        from app.core.redis import redis_client

        pattern = f"cache:*:{self.runtime_id}:*"
        keys = await redis_client.keys(pattern)
        if keys:
            await redis_client.delete(*keys)
        return {"status": "success", "cleared_keys": len(keys)}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


async def _restart_runtime(self: RuntimeAssistantTools) -> dict[str, Any]:
    result = await self.runtime_service.enqueue_build(
        self.runtime_id, trigger="assistant_restart"
    )
    return {"status": "queued", "runtime_id": self.runtime_id, "result": result}


async def _run_health_check(self: RuntimeAssistantTools) -> dict[str, Any]:
    return await self.health_service.get_runtime_health(self.runtime_id)


async def _run_cost_analysis(self: RuntimeAssistantTools) -> dict[str, Any]:
    runtime = await self.runtime_service.get(self.runtime_id)
    if not runtime:
        raise ValueError("Runtime not found")
    from app.services.billing import BillingService

    billing_service = BillingService(self.uow.session)
    summary = await billing_service.get_usage_summary(
        uuid.UUID(self.user_id) if self.user_id else None
    )
    return {
        "runtime_id": self.runtime_id,
        "total_cost": float(summary.get("total_cost", 0)) if summary.get("total_cost") else 0.0,
        "total_requests": summary.get("total_requests", 0),
        "by_provider": summary.get("by_provider", []),
        "by_model": summary.get("by_model", []),
        "by_operation": summary.get("by_operation", []),
    }


async def _generate_report(self: RuntimeAssistantTools, format: str = "markdown") -> dict[str, Any]:
    summary = await _get_runtime_summary(self)
    health = await _get_runtime_health(self)
    billing = await _get_billing(self)

    if format == "json":
        return {"format": "json", "data": {"summary": summary, "health": health, "billing": billing}}
    elif format == "text":
        return {
            "format": "text",
            "report": (
                f"Runtime Report\n"
                f"==============\n"
                f"Status: {summary.get('status')}\n"
                f"Health Score: {summary.get('health_score')}\n"
                f"Provider: {summary.get('provider')}\n"
                f"Model: {summary.get('model')}\n"
                f"Monthly Cost: ${summary.get('monthly_cost', 0):.2f}\n"
                f"Issues: {', '.join(summary.get('issues', [])) or 'None'}"
            ),
        }
    else:
        return {
            "format": "markdown",
            "report": (
                f"# Runtime Report\n\n"
                f"**Status:** {summary.get('status')}\n\n"
                f"**Health Score:** {summary.get('health_score')}\n\n"
                f"**Provider:** {summary.get('provider')}\n\n"
                f"**Model:** {summary.get('model')}\n\n"
                f"**Monthly Cost:** ${summary.get('monthly_cost', 0):.2f}\n\n"
                f"## Issues\n\n"
                f"{chr(10).join(['- ' + i for i in summary.get('issues', [])]) or '- None'}"
            ),
        }


async def _pause_runtime(self: RuntimeAssistantTools) -> dict[str, Any]:
    runtime = await self.runtime_service.get(self.runtime_id)
    if not runtime:
        raise ValueError("Runtime not found")
    updated = await self.runtime_service.update_status(self.runtime_id, "paused")
    await self.uow.commit()
    return {"status": "paused", "runtime_id": self.runtime_id}


async def _resume_runtime(self: RuntimeAssistantTools) -> dict[str, Any]:
    runtime = await self.runtime_service.get(self.runtime_id)
    if not runtime:
        raise ValueError("Runtime not found")
    updated = await self.runtime_service.update_status(self.runtime_id, "active")
    await self.uow.commit()
    return {"status": "active", "runtime_id": self.runtime_id}


async def _rotate_api_key(self: RuntimeAssistantTools) -> dict[str, Any]:
    from app.services.apikeys import ApiKeyService

    api_key_service = ApiKeyService(self.uow.session)
    runtime = await self.runtime_service.get(self.runtime_id)
    if not runtime:
        raise ValueError("Runtime not found")

    api_key_id = runtime.get("api_key_id")
    if not api_key_id:
        return {"status": "error", "error": "No API key associated with runtime"}

    result = await api_key_service.rotate_key(api_key_id)
    await self.uow.commit()
    return {
        "status": "rotated",
        "key_id": str(result.get("api_key", {}).get("id", api_key_id)),
        "prefix": result.get("api_key", {}).get("prefix", ""),
    }


async def _revoke_api_key(self: RuntimeAssistantTools, key_id: str) -> dict[str, Any]:
    from app.services.apikeys import ApiKeyService

    api_key_service = ApiKeyService(self.uow)
    await api_key_service.revoke_key(key_id)
    await self.uow.commit()
    return {"status": "revoked", "key_id": key_id}


async def _test_provider(self: RuntimeAssistantTools, provider_name: str) -> dict[str, Any]:
    result = await self.provider_service.test_connection(
        {"provider_name": provider_name, "project_id": self.project_id}
    )
    return {"provider": provider_name, "test_result": result}


async def _test_database(self: RuntimeAssistantTools) -> dict[str, Any]:
    try:
        from app.core.database import async_session_factory
        from sqlalchemy import text

        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "connected", "database": "operational"}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


async def _test_tool(self: RuntimeAssistantTools, tool_id: str) -> dict[str, Any]:
    tool = await self.uow.tools.get(tool_id)
    if not tool:
        raise ValueError("Tool not found")
    return {"tool_id": tool_id, "name": tool.name, "status": "tested", "result": "ok"}


async def _generate_runtime_summary(self: RuntimeAssistantTools) -> dict[str, Any]:
    summary = await _get_runtime_summary(self)
    return {
        "summary": summary,
        "recommendations": [
            "Enable dynamic routing if disabled",
            "Review expensive models",
            "Sync failed knowledge sources",
        ],
    }


_TOOL_MAP: dict[str, Any] = {
    "get_runtime_summary": _get_runtime_summary,
    "get_runtime_health": _get_runtime_health,
    "get_runtime_config": _get_runtime_config,
    "get_providers": _get_providers,
    "get_models": _get_models,
    "get_knowledge_sources": _get_knowledge_sources,
    "get_tools": _get_tools,
    "get_logs": _get_logs,
    "get_analytics": _get_analytics,
    "get_billing": _get_billing,
    "get_security_settings": _get_security_settings,
    "get_deployment_status": _get_deployment_status,
    "get_change_history": _get_change_history,
    "enable_dynamic_routing": _enable_dynamic_routing,
    "disable_dynamic_routing": _disable_dynamic_routing,
    "change_default_provider": _change_default_provider,
    "change_temperature": _change_temperature,
    "change_max_tokens": _change_max_tokens,
    "update_runtime_configuration": _update_runtime_configuration,
    "sync_sources": _sync_sources,
    "rebuild_embeddings": _rebuild_embeddings,
    "clear_cache": _clear_cache,
    "restart_runtime": _restart_runtime,
    "run_health_check": _run_health_check,
    "run_cost_analysis": _run_cost_analysis,
    "generate_report": _generate_report,
    "pause_runtime": _pause_runtime,
    "resume_runtime": _resume_runtime,
    "rotate_api_key": _rotate_api_key,
    "revoke_api_key": _revoke_api_key,
    "test_provider": _test_provider,
    "test_database": _test_database,
    "test_tool": _test_tool,
    "generate_runtime_summary": _generate_runtime_summary,
}

_ALL_TOOLS: list[ToolDefinition] = []


def _build_all_tools() -> list[ToolDefinition]:
    from app.services.runtime_assistant.prompts import build_tool_definitions

    return build_tool_definitions()


_ALL_TOOLS = _build_all_tools()
