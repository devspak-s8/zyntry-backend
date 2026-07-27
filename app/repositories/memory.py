from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory import MemoryRecord


class MemoryRecordRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_project(self, project_id: uuid.UUID) -> list[MemoryRecord]:
        result = await self.session.execute(
            select(MemoryRecord).where(MemoryRecord.project_id == project_id)
        )
        return list(result.scalars().all())

    async def get_by_key(self, project_id: uuid.UUID, key: str) -> MemoryRecord | None:
        result = await self.session.execute(
            select(MemoryRecord).where(
                MemoryRecord.project_id == project_id,
                MemoryRecord.key == key,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_key_and_scope(
        self,
        project_id: uuid.UUID,
        key: str,
        user_id: uuid.UUID | None = None,
        conversation_id: uuid.UUID | None = None,
        session_id: str | None = None,
    ) -> MemoryRecord | None:
        stmt = select(MemoryRecord).where(
            MemoryRecord.project_id == project_id,
            MemoryRecord.key == key,
        )
        if user_id is not None:
            stmt = stmt.where(MemoryRecord.user_id == user_id)
        else:
            stmt = stmt.where(MemoryRecord.user_id.is_(None))
        if conversation_id is not None:
            stmt = stmt.where(MemoryRecord.conversation_id == conversation_id)
        else:
            stmt = stmt.where(MemoryRecord.conversation_id.is_(None))
        if session_id is not None:
            stmt = stmt.where(MemoryRecord.session_id == session_id)
        else:
            stmt = stmt.where(MemoryRecord.session_id.is_(None))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_conversation_id(
        self, conversation_id: uuid.UUID
    ) -> list[MemoryRecord]:
        result = await self.session.execute(
            select(MemoryRecord).where(
                MemoryRecord.conversation_id == conversation_id
            )
        )
        return list(result.scalars().all())

    async def get_by_session_id(self, session_id: str) -> list[MemoryRecord]:
        result = await self.session.execute(
            select(MemoryRecord).where(MemoryRecord.session_id == session_id)
        )
        return list(result.scalars().all())

    async def get_by_user(
        self,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
        memory_type: str | None = None,
    ) -> list[MemoryRecord]:
        stmt = select(MemoryRecord).where(
            MemoryRecord.project_id == project_id,
            MemoryRecord.user_id == user_id,
        )
        if memory_type:
            stmt = stmt.where(MemoryRecord.memory_type == memory_type)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_parent_key(self, parent_key: str) -> MemoryRecord | None:
        result = await self.session.execute(
            select(MemoryRecord).where(MemoryRecord.parent_key == parent_key)
        )
        return result.scalar_one_or_none()

    async def get_expired(self, now: datetime) -> list[MemoryRecord]:
        result = await self.session.execute(
            select(MemoryRecord).where(
                MemoryRecord.expires_at.is_not(None),
                MemoryRecord.expires_at < now,
                MemoryRecord.pinned.is_(False),
            )
        )
        return list(result.scalars().all())

    async def list_by_scope(
        self,
        project_id: uuid.UUID,
        user_id: uuid.UUID | None = None,
        memory_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryRecord]:
        stmt = select(MemoryRecord).where(MemoryRecord.project_id == project_id)
        if user_id is not None:
            stmt = stmt.where(MemoryRecord.user_id == user_id)
        if memory_type:
            stmt = stmt.where(MemoryRecord.memory_type == memory_type)
        stmt = (
            stmt.order_by(MemoryRecord.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def search(
        self,
        project_id: uuid.UUID,
        query: str,
        user_id: uuid.UUID | None = None,
        memory_type: str | None = None,
        limit: int = 10,
    ) -> list[MemoryRecord]:
        pattern = f"%{query}%"
        stmt = select(MemoryRecord).where(
            MemoryRecord.project_id == project_id,
            or_(
                MemoryRecord.content.ilike(pattern),
                MemoryRecord.key.ilike(pattern),
            ),
        )
        if user_id is not None:
            stmt = stmt.where(MemoryRecord.user_id == user_id)
        if memory_type:
            stmt = stmt.where(MemoryRecord.memory_type == memory_type)
        stmt = stmt.order_by(MemoryRecord.created_at.desc()).limit(limit * 3)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, **kwargs: object) -> MemoryRecord:
        record = MemoryRecord(**kwargs)
        self.session.add(record)
        await self.session.flush()
        return record

    async def update(self, instance: MemoryRecord, **kwargs: object) -> MemoryRecord:
        for key, value in kwargs.items():
            setattr(instance, key, value)
        await self.session.flush()
        return instance

    async def delete(self, instance: MemoryRecord) -> None:
        await self.session.delete(instance)
        await self.session.flush()
