from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.core.database import get_session
from app.models.users import User
from app.repositories import UnitOfWork
from app.schemas.tools import ToolCreate, ToolRead, ToolUpdate
from app.services.tools import ToolService

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("", response_model=list[ToolRead])
async def list_tools(
    current_user: Annotated[User, Depends(get_current_user)],
    project_id: str | None = None,
    db: AsyncSession = Depends(get_session),
) -> list[ToolRead]:
    uow = UnitOfWork(db)
    service = ToolService(uow)
    tools = await service.list_tools(project_id)
    return [
        ToolRead(
            id=t["id"],
            name=t["name"],
            description=t.get("description"),
            schema=t.get("schema", {}),
            implementation=t.get("implementation"),
            project_id=t.get("project_id"),
            created_at=t.get("created_at", ""),
            updated_at=t.get("created_at", ""),
        )
        for t in tools
    ]


@router.post("", response_model=ToolRead, status_code=status.HTTP_201_CREATED)
async def create_tool(
    body: ToolCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> ToolRead:
    uow = UnitOfWork(db)
    service = ToolService(uow)
    tool = await service.create_tool(body)
    return ToolRead(
        id=tool["id"],
        name=tool["name"],
        description=tool.get("description"),
        schema=tool.get("schema", {}),
        implementation=tool.get("implementation"),
        project_id=tool.get("project_id"),
        created_at="",
        updated_at="",
    )


@router.patch("/{tool_id}", response_model=ToolRead)
async def update_tool(
    tool_id: str,
    body: ToolUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> ToolRead:
    uow = UnitOfWork(db)
    service = ToolService(uow)
    tool = await service.update_tool(tool_id, body)
    return ToolRead(
        id=tool["id"],
        name=tool["name"],
        description=tool.get("description"),
        schema=tool.get("schema", {}),
        implementation=tool.get("implementation"),
        project_id=None,
        created_at="",
        updated_at="",
    )


@router.delete("/{tool_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tool(
    tool_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> None:
    uow = UnitOfWork(db)
    service = ToolService(uow)
    await service.delete_tool(tool_id)
