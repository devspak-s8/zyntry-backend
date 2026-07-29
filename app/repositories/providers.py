from __future__ import annotations

import uuid
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.onboarding import ProviderConnection


class ProviderConnectionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, connection_id: str | UUID) -> ProviderConnection | None:
        if isinstance(connection_id, str):
            connection_id = uuid.UUID(connection_id)
        return await self.session.get(ProviderConnection, connection_id)

    async def get_by_project(self, project_id: str | UUID) -> list[ProviderConnection]:
        if isinstance(project_id, str):
            project_id = UUID(project_id)
        result = await self.session.execute(
            select(ProviderConnection).where(ProviderConnection.project_id == project_id)
        )
        return list(result.scalars().all())

    async def get_by_org(self, organization_id: str | UUID) -> list[ProviderConnection]:
        if isinstance(organization_id, str):
            organization_id = UUID(organization_id)
        result = await self.session.execute(
            select(ProviderConnection).where(ProviderConnection.organization_id == organization_id)
        )
        return list(result.scalars().all())

    async def get_by_provider(
        self, project_id: str | UUID, provider_name: str
    ) -> ProviderConnection | None:
        if isinstance(project_id, str):
            project_id = UUID(project_id)
        result = await self.session.execute(
            select(ProviderConnection).where(
                ProviderConnection.project_id == project_id,
                ProviderConnection.provider_name == provider_name,
            )
        )
        return result.scalar_one_or_none()

    async def list(self) -> list[ProviderConnection]:
        result = await self.session.execute(select(ProviderConnection))
        return list(result.scalars().all())

    async def create(self, **kwargs: object) -> ProviderConnection:
        conn = ProviderConnection(**kwargs)
        self.session.add(conn)
        await self.session.flush()
        return conn

    async def update(self, instance: ProviderConnection, **kwargs: object) -> ProviderConnection:
        for key, value in kwargs.items():
            setattr(instance, key, value)
        await self.session.flush()
        return instance

    async def delete(self, instance: ProviderConnection) -> None:
        await self.session.delete(instance)
        await self.session.flush()
