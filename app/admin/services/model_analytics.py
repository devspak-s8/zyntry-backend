from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing import UsageLog


class ModelAnalyticsService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_provider_model_analytics(self, since: datetime | None = None) -> list[dict[str, Any]]:
        if since is None:
            since = datetime.now(UTC) - timedelta(days=30)

        result = await self.db.execute(
            select(
                UsageLog.provider,
                UsageLog.model,
                func.coalesce(func.sum(UsageLog.requests), 0).label("requests"),
                func.coalesce(func.avg(UsageLog.latency_ms), 0).label("avg_latency"),
                func.coalesce(func.sum(UsageLog.cost), 0).label("cost"),
                func.coalesce(func.avg(UsageLog.input_tokens + UsageLog.output_tokens), 0).label("avg_tokens"),
            )
            .where(UsageLog.created_at >= since)
            .group_by(UsageLog.provider, UsageLog.model)
            .order_by(func.sum(UsageLog.requests).desc())
        )
        rows = result.all()
        output = []
        for provider, model, requests, avg_latency, cost, avg_tokens in rows:
            failure_rows = await self.db.execute(
                select(UsageLog.metadata_).where(
                    UsageLog.provider == provider,
                    UsageLog.model == model,
                    UsageLog.created_at >= since,
                )
            )
            failures = sum(
                1 for (metadata,) in failure_rows.all()
                if isinstance(metadata, dict) and (metadata.get("error") or metadata.get("success") is False)
            )
            request_count = int(requests or 0)
            recommendation = ""
            is_recommended = False
            output.append({
                "provider": provider,
                "model": model,
                "requests": request_count,
                "avg_latency_ms": float(avg_latency or 0),
                "avg_cost": float(cost or 0) / request_count if request_count else 0.0,
                "cost": Decimal(str(cost or 0)),
                "failures": failures,
                "avg_tokens": int(avg_tokens or 0),
                "success_rate": max(0.0, (request_count - failures) / request_count) if request_count else 1.0,
                "is_recommended": is_recommended,
                "recommendation_reason": recommendation,
            })
        return output

    async def _estimate_success(self, provider: str, model: str, since: datetime) -> float:
        return 1.0

    async def get_provider_recommendations(self, analytics: list[dict[str, Any]]) -> list[dict[str, Any]]:
        recommendations = []
        for entry in analytics:
            provider = entry.get("provider", "")
            p = {
                "provider": provider,
                "total_requests": entry.get("requests", 0),
                "requests": entry.get("requests", 0),
                "total_latency": entry.get("avg_latency_ms", 0),
                "latency_ms": entry.get("avg_latency_ms", 0),
                "total_cost": float(entry.get("cost", 0)),
                "cost": float(entry.get("cost", 0)),
                "total_failures": entry.get("failures", 0),
                "failures": entry.get("failures", 0),
                "models": [{"model": entry.get("model", "")}],
                "model": entry.get("model", ""),
            }
            recommendations.append(p)
        return recommendations

    async def get_provider_performance(self, since: datetime | None = None) -> list[dict[str, Any]]:
        if since is None:
            since = datetime.now(UTC) - timedelta(days=30)
        result = await self.db.execute(
            select(
                UsageLog.provider,
                func.coalesce(func.sum(UsageLog.requests), 0).label("requests"),
                func.coalesce(func.avg(UsageLog.latency_ms), 0).label("avg_latency"),
                func.coalesce(func.sum(UsageLog.cost), 0).label("cost"),
            )
            .where(UsageLog.created_at >= since)
            .group_by(UsageLog.provider)
            .order_by(func.sum(UsageLog.requests).desc())
        )
        output = []
        for provider, requests, avg_latency, cost in result.all():
            request_count = int(requests or 0)
            failure_rows = await self.db.execute(
                select(UsageLog.metadata_).where(UsageLog.provider == provider, UsageLog.created_at >= since)
            )
            failures = sum(
                1 for (metadata,) in failure_rows.all()
                if isinstance(metadata, dict) and (metadata.get("error") or metadata.get("success") is False)
            )
            output.append({
                "provider": provider,
                "total_requests": request_count,
                "avg_latency_ms": float(avg_latency or 0),
                "avg_cost": float(cost or 0) / request_count if request_count else 0.0,
                "total_failures": failures,
                "success_rate": max(0.0, (request_count - failures) / request_count) if request_count else 1.0,
                "is_recommended": False,
                "recommendation_reason": None,
            })
        return output
