from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.integrations import IntegrationConnection, RuntimeIntegration


class RuntimeIntegrationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_runtime(self, runtime_id: UUID) -> list[RuntimeIntegration]:
        result = await self.session.execute(
            select(RuntimeIntegration).where(RuntimeIntegration.runtime_id == runtime_id)
        )
        return list(result.scalars().all())

    async def get_by_runtime_and_slug(self, runtime_id: UUID, slug: str) -> RuntimeIntegration | None:
        result = await self.session.execute(
            select(RuntimeIntegration)
            .where(RuntimeIntegration.runtime_id == runtime_id)
            .where(RuntimeIntegration.integration_slug == slug)
        )
        return result.scalars().first()

    async def create(self, **kwargs: object) -> RuntimeIntegration:
        item = RuntimeIntegration(**kwargs)
        self.session.add(item)
        await self.session.flush()
        return item

    async def update(self, instance: RuntimeIntegration, **kwargs: object) -> RuntimeIntegration:
        for key, value in kwargs.items():
            setattr(instance, key, value)
        await self.session.flush()
        return instance

    async def delete(self, instance: RuntimeIntegration) -> None:
        await self.session.delete(instance)
        await self.session.flush()


class IntegrationConnectionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, id: UUID) -> IntegrationConnection | None:
        return await self.session.get(IntegrationConnection, id)

    async def get_by_user(self, user_id: UUID) -> list[IntegrationConnection]:
        result = await self.session.execute(
            select(IntegrationConnection).where(IntegrationConnection.user_id == user_id)
        )
        return list(result.scalars().all())

    async def get_by_runtime(self, runtime_id: UUID) -> list[IntegrationConnection]:
        result = await self.session.execute(
            select(IntegrationConnection).where(IntegrationConnection.runtime_id == runtime_id)
        )
        return list(result.scalars().all())

    async def get_for_end_user(
        self, runtime_id: UUID, integration_slug: str, end_user_id: str
    ) -> IntegrationConnection | None:
        result = await self.session.execute(
            select(IntegrationConnection)
            .where(IntegrationConnection.runtime_id == runtime_id)
            .where(IntegrationConnection.integration_slug == integration_slug)
            .where(IntegrationConnection.end_user_id == end_user_id)
            .where(IntegrationConnection.status == "active")
        )
        return result.scalars().first()

    async def get_zyntry_managed(
        self, user_id: UUID, integration_slug: str
    ) -> IntegrationConnection | None:
        result = await self.session.execute(
            select(IntegrationConnection)
            .where(IntegrationConnection.user_id == user_id)
            .where(IntegrationConnection.integration_slug == integration_slug)
            .where(IntegrationConnection.connection_mode == "zyntry_managed")
            .where(IntegrationConnection.status == "active")
        )
        return result.scalars().first()

    async def list_connections(
        self,
        user_id: UUID | None = None,
        runtime_id: UUID | None = None,
        integration_slug: str | None = None,
        end_user_id: str | None = None,
        connection_mode: str | None = None,
    ) -> list[IntegrationConnection]:
        stmt = select(IntegrationConnection)
        if user_id is not None:
            stmt = stmt.where(IntegrationConnection.user_id == user_id)
        if runtime_id is not None:
            stmt = stmt.where(IntegrationConnection.runtime_id == runtime_id)
        if integration_slug is not None:
            stmt = stmt.where(IntegrationConnection.integration_slug == integration_slug)
        if end_user_id is not None:
            stmt = stmt.where(IntegrationConnection.end_user_id == end_user_id)
        if connection_mode is not None:
            stmt = stmt.where(IntegrationConnection.connection_mode == connection_mode)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, **kwargs: object) -> IntegrationConnection:
        conn = IntegrationConnection(**kwargs)
        self.session.add(conn)
        await self.session.flush()
        return conn

    async def update(self, instance: IntegrationConnection, **kwargs: object) -> IntegrationConnection:
        for key, value in kwargs.items():
            setattr(instance, key, value)
        await self.session.flush()
        return instance

    async def delete(self, instance: IntegrationConnection) -> None:
        await self.session.delete(instance)
        await self.session.flush()
