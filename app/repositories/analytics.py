from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analytics import UsageEvent


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
        if not row:
            return {
                "total_requests": 0,
                "total_tokens": 0,
                "total_cost_cents": 0,
                "avg_latency_ms": 0,
                "error_count": 0,
                "provider_breakdown": {},
                "model_breakdown": {},
            }
        return {
            "total_requests": row.total_requests or 0,
            "total_tokens": row.total_quantity or 0,
            "total_cost_cents": 0,
            "avg_latency_ms": 0,
            "error_count": 0,
            "provider_breakdown": {},
            "model_breakdown": {},
        }
