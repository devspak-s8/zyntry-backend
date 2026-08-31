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

        # These dimensions are optional in the usage schema and are recorded
        # in metadata by runtimes that support them. Read them defensively so
        # analytics still works for older usage rows.
        metadata_result = await self.db.execute(
            select(UsageLog.metadata_, UsageLog.requests, UsageLog.cost)
            .where(UsageLog.created_at >= since)
        )
        dimensions: dict[str, dict[str, list[float]]] = {
            "knowledge_source_id": {},
            "tool_id": {},
            "endpoint": {},
        }
        for metadata, requests, cost in metadata_result.all():
            if not isinstance(metadata, dict):
                continue
            for field in dimensions:
                value = metadata.get(field)
                if value is None:
                    continue
                key = str(value)
                bucket = dimensions[field].setdefault(key, [0.0, 0.0])
                bucket[0] += float(requests or 1)
                bucket[1] += float(cost or 0)

        top_knowledge_sources = [
            {"source_id": key, "request_count": int(values[0]), "total_cost": values[1]}
            for key, values in sorted(dimensions["knowledge_source_id"].items(), key=lambda item: item[1][0], reverse=True)[:10]
        ]
        top_tools = [
            {"tool_id": key, "request_count": int(values[0]), "total_cost": values[1]}
            for key, values in sorted(dimensions["tool_id"].items(), key=lambda item: item[1][0], reverse=True)[:10]
        ]
        top_endpoints = [
            {"endpoint": key, "request_count": int(values[0]), "total_cost": values[1]}
            for key, values in sorted(dimensions["endpoint"].items(), key=lambda item: item[1][0], reverse=True)[:10]
        ]

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
