from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.onboarding import ProviderConnection


class ProviderConnectionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_project(self, project_id: UUID) -> list[ProviderConnection]:
        result = await self.session.execute(
            select(ProviderConnection).where(ProviderConnection.project_id == project_id)
        )
        return list(result.scalars().all())

    async def get_by_org(self, organization_id: UUID) -> list[ProviderConnection]:
        result = await self.session.execute(
            select(ProviderConnection).where(ProviderConnection.organization_id == organization_id)
        )
        return list(result.scalars().all())

    async def get_by_provider(self, project_id: UUID, provider_name: str) -> ProviderConnection | None:
        result = await self.session.execute(
            select(ProviderConnection).where(
                ProviderConnection.project_id == project_id,
                ProviderConnection.provider_name == provider_name,
            )
        )
        return result.scalar_one_or_none()

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
