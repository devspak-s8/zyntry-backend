from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.runtimes import Runtime, RuntimeBuildChunk, RuntimeBuildLog


class RuntimeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_project(self, project_id: UUID) -> Runtime | None:
        result = await self.session.execute(
            select(Runtime).where(Runtime.project_id == project_id)
        )
        return result.scalars().first()

    async def get(self, id: UUID) -> Runtime | None:
        return await self.session.get(Runtime, id)

    async def get_by_organization(self, organization_id: UUID) -> list[Runtime]:
        result = await self.session.execute(
            select(Runtime).where(Runtime.organization_id == organization_id)
        )
        return list(result.scalars().all())

    async def create(self, **kwargs: object) -> Runtime:
        runtime = Runtime(**kwargs)
        self.session.add(runtime)
        await self.session.flush()
        return runtime

    async def update(self, instance: Runtime, **kwargs: object) -> Runtime:
        for key, value in kwargs.items():
            setattr(instance, key, value)
        await self.session.flush()
        return instance

    async def delete(self, instance: Runtime) -> None:
        await self.session.delete(instance)
        await self.session.flush()

    async def list_active(self, limit: int = 50, offset: int = 0) -> list[Runtime]:
        result = await self.session.execute(
            select(Runtime)
            .where(Runtime.status == "active")
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())


class RuntimeBuildLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_runtime(self, runtime_id: UUID) -> list[RuntimeBuildLog]:
        result = await self.session.execute(
            select(RuntimeBuildLog)
            .where(RuntimeBuildLog.runtime_id == runtime_id)
            .order_by(RuntimeBuildLog.created_at.asc())
        )
        return list(result.scalars().all())

    async def get(self, id: UUID) -> RuntimeBuildLog | None:
        return await self.session.get(RuntimeBuildLog, id)

    async def create(self, **kwargs: object) -> RuntimeBuildLog:
        log = RuntimeBuildLog(**kwargs)
        self.session.add(log)
        await self.session.flush()
        return log

    async def update(self, instance: RuntimeBuildLog, **kwargs: object) -> RuntimeBuildLog:
        for key, value in kwargs.items():
            setattr(instance, key, value)
        await self.session.flush()
        return instance

    async def delete(self, instance: RuntimeBuildLog) -> None:
        await self.session.delete(instance)
        await self.session.flush()

    async def delete_by_runtime(self, runtime_id: UUID) -> None:
        await self.session.execute(
            delete(RuntimeBuildLog).where(RuntimeBuildLog.runtime_id == runtime_id)
        )
        await self.session.flush()


class RuntimeBuildChunkRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_runtime(self, runtime_id: UUID) -> list[RuntimeBuildChunk]:
        result = await self.session.execute(
            select(RuntimeBuildChunk).where(RuntimeBuildChunk.runtime_id == runtime_id)
        )
        return list(result.scalars().all())

    async def get_by_document(self, runtime_id: UUID, document_id: UUID) -> list[RuntimeBuildChunk]:
        result = await self.session.execute(
            select(RuntimeBuildChunk)
            .where(RuntimeBuildChunk.runtime_id == runtime_id)
            .where(RuntimeBuildChunk.document_id == document_id)
        )
        return list(result.scalars().all())

    async def get(self, id: UUID) -> RuntimeBuildChunk | None:
        return await self.session.get(RuntimeBuildChunk, id)

    async def create(self, **kwargs: object) -> RuntimeBuildChunk:
        chunk = RuntimeBuildChunk(**kwargs)
        self.session.add(chunk)
        await self.session.flush()
        return chunk

    async def bulk_create(self, chunks: list[dict]) -> list[RuntimeBuildChunk]:
        instances = [RuntimeBuildChunk(**c) for c in chunks]
        self.session.add_all(instances)
        await self.session.flush()
        return instances

    async def delete(self, instance: RuntimeBuildChunk) -> None:
        await self.session.delete(instance)
        await self.session.flush()

    async def delete_by_runtime(self, runtime_id: UUID) -> None:
        await self.session.execute(
            delete(RuntimeBuildChunk).where(RuntimeBuildChunk.runtime_id == runtime_id)
        )
        await self.session.flush()
