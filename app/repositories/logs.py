from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.request_logs import RequestLog
from app.repositories.base import BaseRepository


class RequestLogRepository(BaseRepository[RequestLog]):
    model = RequestLog

    async def list_for_project(self, project_id: uuid.UUID, limit: int = 50, offset: int = 0) -> list[RequestLog]:
        result = await self.session.execute(
            select(self.model)
            .where(self.model.project_id == project_id)
            .order_by(self.model.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())
