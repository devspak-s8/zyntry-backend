from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.notifications import Notification
from app.repositories.base import BaseRepository


class NotificationRepository(BaseRepository[Notification]):
    model = Notification

    async def list_for_user(self, user_id: uuid.UUID, limit: int = 50, offset: int = 0) -> list[Notification]:
        result = await self.session.execute(
            select(self.model)
            .where(self.model.user_id == user_id)
            .order_by(self.model.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_unread_for_user(self, user_id: uuid.UUID) -> list[Notification]:
        result = await self.session.execute(
            select(self.model).where(self.model.user_id == user_id, self.model.read == False)
        )
        return list(result.scalars().all())
