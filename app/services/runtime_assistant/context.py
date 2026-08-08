from __future__ import annotations

from typing import Any

from app.repositories import UnitOfWork
from app.services.analytics import AnalyticsService
from app.services.billing import BillingService
from app.services.health import HealthService
from app.services.knowledge import KnowledgeService
from app.services.providers import ProviderService
from app.services.runtimes import RuntimeService
from app.services.tools import ToolService
from app.services.runtime_assistant.schemas import RuntimeContext


class RuntimeContextBuilder:
    def __init__(self, uow: UnitOfWork, runtime_id: str, user_id: str, user_role: str) -> None:
        self.uow = uow
        self.runtime_id = runtime_id
        self.user_id = user_id
        self.user_role = user_role
        self.runtime_service = RuntimeService(uow)
        self.provider_service = ProviderService(uow)
        self.knowledge_service = KnowledgeService(uow)
        self.tool_service = ToolService(uow)
        self.health_service = HealthService(uow)
        self.analytics_service = AnalyticsService(uow)
        self.billing_service = BillingService(uow.session)

    async def build(self) -> RuntimeContext:
        runtime = await self.runtime_service.get(self.runtime_id)
        if not runtime:
            raise ValueError(f"Runtime {self.runtime_id} not found")

        project_id = runtime.get("project_id", "")
        organization_id = runtime.get("organization_id", "")

        providers = await self.provider_service.list_providers(project_id)
        knowledge_sources = await self.knowledge_service.list_sources(project_id)
        tools = await self.tool_service.list_tools(project_id)
        health = await self.health_service.get_runtime_health(self.runtime_id)
        analytics = await self.analytics_service.get_summary(project_id)
        billing_summary = await self.billing_service.get_usage_summary(
            uuid.UUID(self.user_id) if self.user_id else None
        )

        return RuntimeContext(
            runtime_id=self.runtime_id,
            project_id=project_id,
            organization_id=organization_id,
            user_id=self.user_id,
            user_role=self.user_role,
            runtime=runtime,
            providers=providers,
            models=self._build_models(providers),
            knowledge_sources=knowledge_sources,
            tools=tools,
            logs=await self._get_recent_logs(project_id),
            analytics=self._serialize_analytics(analytics),
            billing=self._serialize_billing(billing_summary),
            health=health,
            config=runtime.get("config", {}),
            security=await self._get_security_settings(),
            deployment=self._get_deployment_status(runtime),
        )

    def _build_models(self, providers: list[dict[str, Any]]) -> list[dict[str, Any]]:
        models: list[dict[str, Any]] = []
        for provider in providers:
            provider_name = provider.get("provider_name", "")
            if provider_name:
                models.append(
                    {
                        "provider": provider_name,
                        "display_name": provider.get("display_name", provider_name),
                        "status": provider.get("status", "unknown"),
                    }
                )
        return models

    async def _get_recent_logs(self, project_id: str, limit: int = 50) -> list[dict[str, Any]]:
        from app.repositories.request_logs import RequestLogRepository

        request_logs = []
        try:
            repo = RequestLogRepository(self.uow.session)
            logs = await repo.list(limit=limit, offset=0)
            request_logs = [log for log in logs if str(log.project_id) == str(project_id)]
        except Exception:
            pass

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
            for log in request_logs
        ]

    def _serialize_analytics(self, analytics: dict[str, Any]) -> dict[str, Any]:
        if not analytics:
            return {}
        serialized = dict(analytics)
        for key in ("total_cost",):
            if key in serialized and hasattr(serialized[key], "__float__"):
                serialized[key] = float(serialized[key])
        return serialized

    def _serialize_billing(self, billing: dict[str, Any]) -> dict[str, Any]:
        if not billing:
            return {}
        serialized = dict(billing)
        for key in ("total_cost",):
            if key in serialized and hasattr(serialized[key], "__float__"):
                serialized[key] = float(serialized[key])
        return serialized

    async def _get_security_settings(self) -> dict[str, Any]:
        try:
            from app.services.apikeys import ApiKeyService

            api_key_service = ApiKeyService(self.uow)
            keys = await api_key_service.list_keys()
            return {
                "api_keys_count": len(keys),
                "keys": [
                    {
                        "id": str(k.id),
                        "name": k.name,
                        "prefix": k.prefix,
                        "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
                        "expires_at": k.expires_at.isoformat() if k.expires_at else None,
                        "revoked": k.revoked,
                    }
                    for k in keys
                ],
            }
        except Exception:
            return {"api_keys_count": 0, "keys": []}

    def _get_deployment_status(self, runtime: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": runtime.get("status", "unknown"),
            "version": runtime.get("version", "unknown"),
            "last_build_completed": runtime.get("last_build_completed"),
            "last_propagated": runtime.get("last_propagated"),
            "health": runtime.get("health", 0.0),
            "error_message": runtime.get("error_message"),
        }
