from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import Document, KnowledgeBase, KnowledgeSource, SyncJob, SyncSchedule


class KnowledgeBaseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_project(self, project_id: UUID) -> list[KnowledgeBase]:
        result = await self.session.execute(
            select(KnowledgeBase).where(KnowledgeBase.project_id == project_id)
        )
        return list(result.scalars().all())

    async def get(self, id: UUID) -> KnowledgeBase | None:
        return await self.session.get(KnowledgeBase, id)

    async def create(self, **kwargs: object) -> KnowledgeBase:
        kb = KnowledgeBase(**kwargs)
        self.session.add(kb)
        await self.session.flush()
        return kb

    async def update(self, instance: KnowledgeBase, **kwargs: object) -> KnowledgeBase:
        for key, value in kwargs.items():
            setattr(instance, key, value)
        await self.session.flush()
        return instance

    async def delete(self, instance: KnowledgeBase) -> None:
        await self.session.delete(instance)
        await self.session.flush()


class DocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_kb(self, knowledge_base_id: UUID) -> list[Document]:
        result = await self.session.execute(
            select(Document).where(Document.knowledge_base_id == knowledge_base_id)
        )
        return list(result.scalars().all())

    async def get(self, id: UUID) -> Document | None:
        return await self.session.get(Document, id)

    async def get_by_source(self, knowledge_base_id: UUID, source: str) -> Document | None:
        result = await self.session.execute(
            select(Document).where(
                Document.knowledge_base_id == knowledge_base_id,
                Document.source == source,
            )
        )
        return result.scalars().first()

    async def create(self, **kwargs: object) -> Document:
        doc = Document(**kwargs)
        self.session.add(doc)
        await self.session.flush()
        return doc

    async def update(self, instance: Document, **kwargs: object) -> Document:
        for key, value in kwargs.items():
            setattr(instance, key, value)
        await self.session.flush()
        return instance

    async def delete(self, instance: Document) -> None:
        await self.session.delete(instance)
        await self.session.flush()


class KnowledgeSourceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_project(self, project_id: UUID) -> list[KnowledgeSource]:
        result = await self.session.execute(
            select(KnowledgeSource).where(KnowledgeSource.project_id == project_id)
        )
        return list(result.scalars().all())

    async def get(self, id: UUID) -> KnowledgeSource | None:
        return await self.session.get(KnowledgeSource, id)

    async def create(self, **kwargs: object) -> KnowledgeSource:
        source = KnowledgeSource(**kwargs)
        self.session.add(source)
        await self.session.flush()
        return source

    async def update(self, instance: KnowledgeSource, **kwargs: object) -> KnowledgeSource:
        for key, value in kwargs.items():
            setattr(instance, key, value)
        await self.session.flush()
        return instance

    async def delete(self, instance: KnowledgeSource) -> None:
        await self.session.delete(instance)
        await self.session.flush()


class SyncJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_source(self, source_id: UUID) -> list[SyncJob]:
        result = await self.session.execute(
            select(SyncJob).where(SyncJob.source_id == source_id)
        )
        return list(result.scalars().all())

    async def get(self, id: UUID) -> SyncJob | None:
        return await self.session.get(SyncJob, id)

    async def create(self, **kwargs: object) -> SyncJob:
        job = SyncJob(**kwargs)
        self.session.add(job)
        await self.session.flush()
        return job

    async def update(self, instance: SyncJob, **kwargs: object) -> SyncJob:
        for key, value in kwargs.items():
            setattr(instance, key, value)
        await self.session.flush()
        return instance

    async def delete(self, instance: SyncJob) -> None:
        await self.session.delete(instance)
        await self.session.flush()


class SyncScheduleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_source(self, source_id: UUID) -> list[SyncSchedule]:
        result = await self.session.execute(
            select(SyncSchedule).where(SyncSchedule.source_id == source_id)
        )
        return list(result.scalars().all())

    async def get(self, id: UUID) -> SyncSchedule | None:
        return await self.session.get(SyncSchedule, id)

    async def list(self, limit: int = 100, offset: int = 0) -> list[SyncSchedule]:
        stmt = select(SyncSchedule).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, **kwargs: object) -> SyncSchedule:
        schedule = SyncSchedule(**kwargs)
        self.session.add(schedule)
        await self.session.flush()
        return schedule

    async def update(self, instance: SyncSchedule, **kwargs: object) -> SyncSchedule:
        for key, value in kwargs.items():
            setattr(instance, key, value)
        await self.session.flush()
        return instance

    async def delete(self, instance: SyncSchedule) -> None:
        await self.session.delete(instance)
        await self.session.flush()

