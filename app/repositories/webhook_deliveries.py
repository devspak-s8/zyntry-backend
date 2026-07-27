from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.webhook_deliveries import WebhookDelivery


class WebhookDeliveryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_subscription(self, subscription_id: UUID) -> list[WebhookDelivery]:
        result = await self.session.execute(
            select(WebhookDelivery).where(WebhookDelivery.subscription_id == subscription_id)
        )
        return list(result.scalars().all())

    async def get(self, id: UUID) -> WebhookDelivery | None:
        return await self.session.get(WebhookDelivery, id)

    async def create(self, **kwargs: object) -> WebhookDelivery:
        delivery = WebhookDelivery(**kwargs)
        self.session.add(delivery)
        await self.session.flush()
        return delivery

    async def delete(self, instance: WebhookDelivery) -> None:
        await self.session.delete(instance)
        await self.session.flush()
