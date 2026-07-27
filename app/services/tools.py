from __future__ import annotations

from typing import Any

from app.repositories import UnitOfWork
from app.schemas.tools import ToolCreate, ToolUpdate


class ToolService:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def list_tools(self, project_id: str | None = None) -> list[dict]:
        if project_id:
            tools = await self.uow.tools.get_by_project(project_id)
        else:
            tools = []
        return [
            {
                "id": str(t.id),
                "name": t.name,
                "description": t.description,
                "schema": t.schema,
                "implementation": t.implementation,
                "project_id": str(t.project_id) if t.project_id else None,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in tools
        ]

    async def create_tool(self, data: ToolCreate) -> dict:
        tool = await self.uow.tools.create(
            name=data.name,
            description=data.description,
            schema=data.schema,
            implementation=data.implementation,
            project_id=data.project_id,
        )
        await self.uow.commit()
        return {
            "id": str(tool.id),
            "name": tool.name,
            "description": tool.description,
            "schema": tool.schema,
            "implementation": tool.implementation,
            "project_id": str(tool.project_id) if tool.project_id else None,
        }

    async def update_tool(self, tool_id: str, data: ToolUpdate) -> dict:
        tool = await self.uow.tools.get(tool_id)
        if not tool:
            raise ValueError("Tool not found")
        update_data = data.model_dump(exclude_unset=True)
        updated = await self.uow.tools.update(tool, **update_data)
        await self.uow.commit()
        return {
            "id": str(updated.id),
            "name": updated.name,
            "description": updated.description,
            "schema": updated.schema,
            "implementation": updated.implementation,
        }

    async def delete_tool(self, tool_id: str) -> None:
        tool = await self.uow.tools.get(tool_id)
        if not tool:
            raise ValueError("Tool not found")
        await self.uow.tools.delete(tool)
        await self.uow.commit()
