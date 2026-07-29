from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analytics import UsageEvent
from app.models.billing import UsageLog


class UsageEventRepository:
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
