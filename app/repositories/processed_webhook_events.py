from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.processed_webhook_events import ProcessedWebhookEvent


class ProcessedWebhookEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_event_id(self, event_id: str) -> ProcessedWebhookEvent | None:
        result = await self.session.execute(
            select(ProcessedWebhookEvent).where(ProcessedWebhookEvent.event_id == event_id)
        )
        return result.scalar_one_or_none()

    async def create(self, **kwargs: object) -> ProcessedWebhookEvent:
        event = ProcessedWebhookEvent(**kwargs)
        self.session.add(event)
        await self.session.flush()
        return event
