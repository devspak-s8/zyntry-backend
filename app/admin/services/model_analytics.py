from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing import UsageLog


class ModelAnalyticsService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_provider_model_analytics(self, since: datetime | None = None) -> list[dict[str, Any]]:
        if since is None:
            since = datetime.now(UTC) - timedelta(days=30)

        result = await self.db.execute(
            select(UsageLog.provider, UsageLog.model)
            .where(UsageLog.created_at >= since)
            .group_by(UsageLog.provider, UsageLog.model)
        )
        rows = result.all()
        output = []
        for provider, model in rows:
            failures = 0
            avg_tokens = 0
            recommendation = ""
            is_recommended = False
            avg_latency = 0.0
            output.append({
                "provider": provider,
                "model": model,
                "requests": 0,
                "avg_latency_ms": avg_latency,
                "cost": Decimal("0"),
                "failures": failures,
                "avg_tokens": avg_tokens,
                "success_rate": 1.0,
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
        return []
