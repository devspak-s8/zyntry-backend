from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select

from app.models.webhook_subscriptions import WebhookSubscription
from app.repositories.base import BaseRepository


class WebhookSubscriptionRepository(BaseRepository[WebhookSubscription]):
    model = WebhookSubscription

    async def list_for_project(self, project_id: uuid.UUID) -> list[WebhookSubscription]:
        result = await self.session.execute(
            select(self.model).where(self.model.project_id == project_id)
        )
        return list(result.scalars().all())
