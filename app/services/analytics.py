from __future__ import annotations

import uuid

from app.repositories import UnitOfWork
from app.schemas.analytics import UsageEventCreate


class AnalyticsService:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def list_events(self, project_id: str, limit: int = 100, offset: int = 0) -> list[dict]:
        events = await self.uow.analytics.get_by_project(
            uuid.UUID(project_id), limit=limit, offset=offset
        )
        return [
            {
                "id": str(e.id),
                "metric": e.metric,
                "quantity": e.quantity,
                "model": e.model,
                "provider": e.provider,
                "project_id": str(e.project_id) if e.project_id else None,
                "metadata": e.metadata_,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ]

    async def create_event(self, data: UsageEventCreate) -> dict:
        event = await self.uow.analytics.create(
            metric=data.metric,
            quantity=data.quantity,
            model=data.model,
            provider=data.provider,
            project_id=uuid.UUID(data.project_id) if data.project_id else None,
            metadata=data.metadata,
        )
        await self.uow.commit()
        result = {
            "id": str(event.id),
            "metric": event.metric,
            "quantity": event.quantity,
            "model": event.model,
            "provider": event.provider,
            "project_id": str(event.project_id) if event.project_id else None,
            "created_at": event.created_at.isoformat() if event.created_at else None,
            "metadata": event.metadata_ or {},
        }
        from app.core.runtime_events import publish_runtime_event

        await publish_runtime_event({"type": "analytics.usage.updated", **result})
        return result

    async def get_summary(self, project_id: str) -> dict:
        return await self.uow.analytics.get_summary(uuid.UUID(project_id))

    async def get_token_activity(self, project_id: str, days: int = 30) -> dict:
        result = await self.uow.analytics.get_token_activity(uuid.UUID(project_id), days=days)
        return {"project_id": project_id, **result}
