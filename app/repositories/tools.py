from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tools import Tool


class ToolRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_project(self, project_id: UUID) -> list[Tool]:
        result = await self.session.execute(
            select(Tool).where(Tool.project_id == project_id)
        )
        return list(result.scalars().all())

    async def get(self, id: UUID) -> Tool | None:
        return await self.session.get(Tool, id)

    async def create(self, **kwargs: object) -> Tool:
        tool = Tool(**kwargs)
        self.session.add(tool)
        await self.session.flush()
        return tool

    async def update(self, instance: Tool, **kwargs: object) -> Tool:
        for key, value in kwargs.items():
            setattr(instance, key, value)
        await self.session.flush()
        return instance

    async def delete(self, instance: Tool) -> None:
        await self.session.delete(instance)
        await self.session.flush()
