from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analytics import UsageEvent
from app.models.billing import UsageLog


class UsageEventRepository:
    model = UsageEvent

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_project(self, project_id: UUID, limit: int = 100, offset: int = 0) -> list[UsageEvent]:
        result = await self.session.execute(
            select(UsageEvent)
            .where(UsageEvent.project_id == project_id)
            .order_by(UsageEvent.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def create(self, **kwargs: object) -> UsageEvent:
        event = UsageEvent(**kwargs)
        self.session.add(event)
        await self.session.flush()
        return event

    async def get_summary(self, project_id: UUID) -> dict:
        result = await self.session.execute(
            select(
                func.count(UsageEvent.id).label("total_requests"),
                func.coalesce(func.sum(UsageEvent.quantity), 0).label("total_quantity"),
            )
            .where(UsageEvent.project_id == project_id)
        )
        row = result.one_or_none()

        cost_result = await self.session.execute(
            select(
                func.coalesce(func.sum(UsageLog.cost), 0).label("total_cost"),
                func.coalesce(func.avg(UsageLog.latency_ms), 0).label("avg_latency"),
                func.count().label("total_logs"),
            )
            .where(UsageLog.project_id == project_id)
        )
        cost_row = cost_result.one_or_none()

        provider_result = await self.session.execute(
            select(UsageLog.provider, func.coalesce(func.sum(UsageLog.cost), 0))
            .where(UsageLog.project_id == project_id)
            .group_by(UsageLog.provider)
        )
        provider_breakdown = {row[0]: float(row[1]) for row in provider_result.all() if row[0]}

        model_result = await self.session.execute(
            select(UsageLog.model, func.coalesce(func.sum(UsageLog.cost), 0))
            .where(UsageLog.project_id == project_id)
            .group_by(UsageLog.model)
        )
        model_breakdown = {row[0]: float(row[1]) for row in model_result.all() if row[0]}

        return {
            "total_requests": row.total_requests or 0 if row else 0,
            "total_tokens": int(row.total_quantity or 0) if row else 0,
            "total_cost_cents": int((cost_row.total_cost or 0) * 100) if cost_row else 0,
            "avg_latency_ms": float(cost_row.avg_latency or 0) if cost_row else 0,
            "error_count": 0,
            "provider_breakdown": provider_breakdown,
            "model_breakdown": model_breakdown,
        }

    async def get_token_activity(self, project_id: UUID, days: int = 30) -> dict:
        """Return daily token activity for dashboard charts/heatmaps."""

        days = min(max(days, 1), 366)
        since = datetime.now(UTC) - timedelta(days=days)
        day_expr = func.date(UsageLog.created_at)
        result = await self.session.execute(
            select(
                day_expr.label("day"),
                func.coalesce(func.sum(UsageLog.input_tokens), 0).label("input_tokens"),
                func.coalesce(func.sum(UsageLog.output_tokens), 0).label("output_tokens"),
                func.coalesce(func.sum(UsageLog.cached_tokens), 0).label("cached_tokens"),
                func.count(UsageLog.id).label("requests"),
                func.coalesce(func.sum(UsageLog.cost), 0).label("cost"),
            )
            .where(UsageLog.project_id == project_id, UsageLog.created_at >= since)
            .group_by(day_expr)
            .order_by(day_expr)
        )
        activity: list[dict] = []
        for row in result.all():
            input_tokens = int(row.input_tokens or 0)
            output_tokens = int(row.output_tokens or 0)
            activity.append({
                "day": str(row.day),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cached_tokens": int(row.cached_tokens or 0),
                "total_tokens": input_tokens + output_tokens,
                "requests": int(row.requests or 0),
                "cost": float(row.cost or 0),
            })

        model_result = await self.session.execute(
            select(UsageLog.model, func.coalesce(func.sum(UsageLog.input_tokens + UsageLog.output_tokens), 0))
            .where(UsageLog.project_id == project_id, UsageLog.created_at >= since)
            .group_by(UsageLog.model)
        )
        provider_result = await self.session.execute(
            select(UsageLog.provider, func.coalesce(func.sum(UsageLog.input_tokens + UsageLog.output_tokens), 0))
            .where(UsageLog.project_id == project_id, UsageLog.created_at >= since)
            .group_by(UsageLog.provider)
        )
        return {
            "days": activity,
            "total_tokens": sum(item["total_tokens"] for item in activity),
            "total_requests": sum(item["requests"] for item in activity),
            "total_cost": sum(item["cost"] for item in activity),
            "by_model": {str(row[0]): int(row[1] or 0) for row in model_result.all() if row[0]},
            "by_provider": {str(row[0]): int(row[1] or 0) for row in provider_result.all() if row[0]},
        }
