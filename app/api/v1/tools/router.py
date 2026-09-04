from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.core.database import get_session
from app.models.users import User
from app.repositories import UnitOfWork
from app.api.v1.dependencies_tenant import require_project_membership
from app.schemas.tools import (
    ToolCatalogItem,
    ToolConnectRequest,
    ToolConnectionStatus,
    ToolCreate,
    ToolRead,
    ToolUpdate,
    OpenAPIToolCreate,
    DatabaseToolCreate,
)
from app.services.tools import ToolService

router = APIRouter(prefix="/tools", tags=["tools"])


def _tool_read(tool: dict) -> ToolRead:
    return ToolRead(
        id=tool["id"],
        name=tool["name"],
        description=tool.get("description"),
        schema=tool.get("schema", {}),
        implementation=tool.get("implementation"),
        project_id=tool.get("project_id"),
        created_at=tool.get("created_at", ""),
        updated_at=tool.get("updated_at", ""),
    )


@router.post("/openapi", response_model=ToolRead, status_code=status.HTTP_201_CREATED)
async def create_openapi_tool(
    body: OpenAPIToolCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> ToolRead:
    await require_project_membership(body.project_id, current_user, db)
    try:
        tool = await ToolService(UnitOfWork(db)).create_openapi_tool(
            name=body.name, description=body.description, project_id=body.project_id,
            server_url=body.server_url, spec=body.spec, read_only=body.read_only,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _tool_read(tool)


@router.post("/database", response_model=ToolRead, status_code=status.HTTP_201_CREATED)
async def create_database_tool(
    body: DatabaseToolCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> ToolRead:
    await require_project_membership(body.project_id, current_user, db)
    try:
        tool = await ToolService(UnitOfWork(db)).create_database_tool(
            name=body.name, description=body.description, project_id=body.project_id,
            database_type=body.database_type, schema=body.schema, read_only=body.read_only,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _tool_read(tool)


@router.get("/catalog", response_model=list[ToolCatalogItem])
async def list_tool_catalog(
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[ToolCatalogItem]:
    return [ToolCatalogItem(**item) for item in ToolService.catalog()]


@router.post("/{connector_key}/connect", response_model=ToolConnectionStatus)
async def connect_catalog_tool(
    connector_key: str,
    body: ToolConnectRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> ToolConnectionStatus:
    await require_project_membership(body.project_id, current_user, db)
    service = ToolService(UnitOfWork(db))
    try:
        result = await service.connect_catalog_tool(
            connector_key=connector_key,
            project_id=body.project_id,
            display_name=body.display_name,
            config=body.config,
            credentials=body.credentials,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    return ToolConnectionStatus(**result)


@router.get("/{connector_key}/status", response_model=ToolConnectionStatus)
async def get_catalog_tool_status(
    connector_key: str,
    project_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> ToolConnectionStatus:
    await require_project_membership(project_id, current_user, db)
    service = ToolService(UnitOfWork(db))
    try:
        result = await service.get_catalog_tool_status(connector_key, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    return ToolConnectionStatus(**result)


@router.get("", response_model=list[ToolRead])
async def list_tools(
    current_user: Annotated[User, Depends(get_current_user)],
    project_id: str | None = None,
    db: AsyncSession = Depends(get_session),
) -> list[ToolRead]:
    if project_id:
        await require_project_membership(project_id, current_user, db)
    uow = UnitOfWork(db)
    service = ToolService(uow)
    tools = await service.list_tools(project_id)
    return [_tool_read(t) for t in tools]


@router.post("", response_model=ToolRead, status_code=status.HTTP_201_CREATED)
async def create_tool(
    body: ToolCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> ToolRead:
    await require_project_membership(body.project_id, current_user, db)
    uow = UnitOfWork(db)
    service = ToolService(uow)
    tool = await service.create_tool(body)
    return _tool_read(tool)


@router.patch("/{tool_id}", response_model=ToolRead)
async def update_tool(
    tool_id: str,
    body: ToolUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> ToolRead:
    uow = UnitOfWork(db)
    existing = await uow.tools.get(tool_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Tool not found")
    await require_project_membership(str(existing.project_id), current_user, db)
    service = ToolService(uow)
    tool = await service.update_tool(tool_id, body)
    return _tool_read(tool)


@router.delete("/{tool_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tool(
    tool_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> None:
    uow = UnitOfWork(db)
    existing = await uow.tools.get(tool_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Tool not found")
    await require_project_membership(str(existing.project_id), current_user, db)
    service = ToolService(uow)
    await service.delete_tool(tool_id)
