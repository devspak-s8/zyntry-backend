from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing import UsageLog


class UsageAnalyticsService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    def _window(self, hours: int) -> datetime:
        return datetime.now(UTC) - timedelta(hours=hours)

    async def get_overview(self, hours: int = 24) -> dict[str, Any]:
        since = self._window(hours)

        top_orgs_result = await self.db.execute(
            select(UsageLog.organization_id, func.count(), func.sum(UsageLog.cost))
            .where(UsageLog.created_at >= since, UsageLog.organization_id.is_not(None))
            .group_by(UsageLog.organization_id)
            .order_by(func.count().desc())
            .limit(10)
        )
        top_organizations = []
        for row in top_orgs_result:
            top_organizations.append({"org_id": str(row[0]) if row[0] else "", "request_count": row[1] or 0, "total_cost": float(row[2] or 0)})

        top_users_result = await self.db.execute(
            select(UsageLog.user_id, func.count(), func.sum(UsageLog.cost))
            .where(UsageLog.created_at >= since, UsageLog.user_id.is_not(None))
            .group_by(UsageLog.user_id)
            .order_by(func.count().desc())
            .limit(10)
        )
        top_users = []
        for row in top_users_result:
            top_users.append({"user_id": str(row[0]) if row[0] else "", "request_count": row[1] or 0, "total_cost": float(row[2] or 0)})

        top_api_keys_result = await self.db.execute(
            select(UsageLog.api_key_id, func.count(), func.sum(UsageLog.cost))
            .where(UsageLog.created_at >= since, UsageLog.api_key_id.is_not(None))
            .group_by(UsageLog.api_key_id)
            .order_by(func.count().desc())
            .limit(10)
        )
        top_api_keys = []
        for row in top_api_keys_result:
            top_api_keys.append({"api_key_id": str(row[0]) if row[0] else "", "request_count": row[1] or 0, "total_cost": float(row[2] or 0)})

        top_models_result = await self.db.execute(
            select(UsageLog.model, func.count(), func.sum(UsageLog.cost), func.avg(UsageLog.input_tokens + UsageLog.output_tokens))
            .where(UsageLog.created_at >= since, UsageLog.model.is_not(None))
            .group_by(UsageLog.model)
            .order_by(func.count().desc())
            .limit(10)
        )
        top_models = []
        for row in top_models_result:
            top_models.append({"model": row[0] or "", "request_count": row[1] or 0, "total_cost": float(row[2] or 0), "avg_tokens": float(row[3] or 0)})

        top_providers_result = await self.db.execute(
            select(UsageLog.provider, func.count(), func.sum(UsageLog.cost))
            .where(UsageLog.created_at >= since, UsageLog.provider.is_not(None))
            .group_by(UsageLog.provider)
            .order_by(func.count().desc())
            .limit(10)
        )
        top_providers = []
        for row in top_providers_result:
            top_providers.append({"provider": row[0] or "", "request_count": row[1] or 0, "total_cost": float(row[2] or 0)})

        top_runtimes_result = await self.db.execute(
            select(UsageLog.runtime_id, func.count(), func.sum(UsageLog.cost))
            .where(UsageLog.created_at >= since, UsageLog.runtime_id.is_not(None))
            .group_by(UsageLog.runtime_id)
            .order_by(func.count().desc())
            .limit(10)
        )
        top_runtimes = []
        for row in top_runtimes_result:
            top_runtimes.append({"runtime_id": str(row[0]) if row[0] else "", "request_count": row[1] or 0, "total_cost": float(row[2] or 0)})

        top_knowledge_result = await self.db.execute(
            select(UsageLog.knowledge_source_id, func.count(), func.sum(UsageLog.cost))
            .where(UsageLog.created_at >= since, UsageLog.knowledge_source_id.is_not(None))
            .group_by(UsageLog.knowledge_source_id)
            .order_by(func.count().desc())
            .limit(10)
        )
        top_knowledge_sources = []
        for row in top_knowledge_result:
            top_knowledge_sources.append({"source_id": str(row[0]) if row[0] else "", "request_count": row[1] or 0, "total_cost": float(row[2] or 0)})

        top_tools_result = await self.db.execute(
            select(UsageLog.tool_id, func.count(), func.sum(UsageLog.cost))
            .where(UsageLog.created_at >= since, UsageLog.tool_id.is_not(None))
            .group_by(UsageLog.tool_id)
            .order_by(func.count().desc())
            .limit(10)
        )
        top_tools = []
        for row in top_tools_result:
            top_tools.append({"tool_id": str(row[0]) if row[0] else "", "request_count": row[1] or 0, "total_cost": float(row[2] or 0)})

        top_endpoints_result = await self.db.execute(
            select(UsageLog.endpoint, func.count(), func.sum(UsageLog.cost))
            .where(UsageLog.created_at >= since, UsageLog.endpoint.is_not(None))
            .group_by(UsageLog.endpoint)
            .order_by(func.count().desc())
            .limit(10)
        )
        top_endpoints = []
        for row in top_endpoints_result:
            top_endpoints.append({"endpoint": row[0] or "", "request_count": row[1] or 0, "total_cost": float(row[2] or 0)})

        avg_tokens_result = await self.db.execute(
            select(func.avg(UsageLog.input_tokens + UsageLog.output_tokens)).where(UsageLog.created_at >= since)
        )
        average_token_usage = float(avg_tokens_result.scalar() or 0)

        avg_cost_result = await self.db.execute(
            select(func.avg(UsageLog.cost)).where(UsageLog.created_at >= since)
        )
        average_cost_per_request = float(avg_cost_result.scalar() or 0)

        total_requests_result = await self.db.execute(select(func.count()).select_from(UsageLog).where(UsageLog.created_at >= since))
        total_requests = total_requests_result.scalar() or 0

        total_cost_result = await self.db.execute(select(func.coalesce(func.sum(UsageLog.cost), 0)).where(UsageLog.created_at >= since))
        total_cost = float(total_cost_result.scalar() or 0)

        total_tokens_result = await self.db.execute(select(func.sum(UsageLog.input_tokens + UsageLog.output_tokens)).where(UsageLog.created_at >= since))
        total_tokens = int(total_tokens_result.scalar() or 0)

        return {
            "period_hours": hours,
            "total_requests": total_requests,
            "total_cost": total_cost,
            "total_tokens": total_tokens,
            "avg_tokens_per_request": round(average_token_usage, 2),
            "avg_cost_per_request": round(average_cost_per_request, 4),
            "top_organizations": top_organizations,
            "top_users": top_users,
            "top_api_keys": top_api_keys,
            "top_models": top_models,
            "top_providers": top_providers,
            "top_runtimes": top_runtimes,
            "top_knowledge_sources": top_knowledge_sources,
            "top_tools": top_tools,
            "top_endpoints": top_endpoints,
        }