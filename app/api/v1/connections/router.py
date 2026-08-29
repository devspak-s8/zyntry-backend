from __future__ import annotations

import logging
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.api.v1.dependencies_tenant import require_runtime_access
from app.core.database import get_session
from app.core.ws_events import emit_integration_connection_updated
from app.models.users import User
from app.repositories import UnitOfWork
from app.schemas.integrations import (
    ConnectionAuthorizeRequest,
    ConnectionAuthorizeResponse,
    ConnectionDirectCreate,
    IntegrationConnectionRead,
)
from app.services.connections.service import ConnectionService
from app.services.security.secrets import default_secret_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/connections", tags=["connections"])


def _to_read_dto(conn: Any) -> IntegrationConnectionRead:
    return IntegrationConnectionRead(
        id=conn.id,
        user_id=conn.user_id,
        runtime_id=conn.runtime_id,
        integration_slug=conn.integration_slug,
        connection_mode=conn.connection_mode,
        end_user_id=conn.end_user_id,
        display_name=conn.display_name,
        auth_method=conn.auth_method,
        scopes=conn.scopes or [],
        expires_at=conn.expires_at,
        last_synchronized_at=conn.last_synchronized_at,
        status=conn.status,
        health_status=conn.health_status,
        metadata=default_secret_manager.redact(conn.metadata_ or {}),
        created_at=conn.created_at,
        updated_at=conn.updated_at,
    )


@router.post("/{integration_slug}/authorize", response_model=ConnectionAuthorizeResponse)
async def authorize_connection(
    integration_slug: str,
    body: ConnectionAuthorizeRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> ConnectionAuthorizeResponse:
    if body.runtime_id:
        await require_runtime_access(body.runtime_id, current_user, db)
    uow = UnitOfWork(db)
    service = ConnectionService(uow)
    try:
        return await service.authorize(
            integration_slug=integration_slug.lower(),
            user_id=current_user.id,
            data=body,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{integration_slug}/callback", response_model=IntegrationConnectionRead)
async def connection_callback(
    integration_slug: str,
    code: Annotated[str, Query()] = "",
    state: Annotated[str, Query()] = "",
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_session),
) -> IntegrationConnectionRead:
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing required code or state query parameters")

    uow = UnitOfWork(db)
    service = ConnectionService(uow)
    try:
        conn = await service.handle_callback(
            integration_slug=integration_slug.lower(),
            code=code,
            state=state,
            expected_user_id=current_user.id if current_user else None,
        )
        if current_user:
            try:
                await emit_integration_connection_updated(
                    str(current_user.id),
                    connection_id=str(conn.id),
                    provider=conn.integration_slug,
                    status=conn.status,
                )
            except Exception:
                pass
        return _to_read_dto(conn)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("", response_model=IntegrationConnectionRead, status_code=status.HTTP_201_CREATED)
async def create_direct_connection(
    body: ConnectionDirectCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> IntegrationConnectionRead:
    if body.runtime_id:
        await require_runtime_access(body.runtime_id, current_user, db)
        body = body.model_copy(update={"end_user_id": body.end_user_id})
    uow = UnitOfWork(db)
    service = ConnectionService(uow)
    try:
        conn = await service.create_direct_connection(
            user_id=current_user.id,
            data=body,
        )
        return _to_read_dto(conn)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=list[IntegrationConnectionRead])
async def list_connections(
    current_user: Annotated[User, Depends(get_current_user)],
    runtime_id: Annotated[str | None, Query()] = None,
    end_user_id: Annotated[str | None, Query()] = None,
    integration_slug: Annotated[str | None, Query()] = None,
    connection_mode: Annotated[str | None, Query()] = None,
    db: AsyncSession = Depends(get_session),
) -> list[IntegrationConnectionRead]:
    if runtime_id:
        await require_runtime_access(runtime_id, current_user, db)
    uow = UnitOfWork(db)
    service = ConnectionService(uow)
    conns = await service.list_connections(
        user_id=current_user.id,
        runtime_id=runtime_id,
        end_user_id=end_user_id,
        integration_slug=integration_slug,
        connection_mode=connection_mode,
    )
    return [_to_read_dto(c) for c in conns]


@router.get("/{connection_id}", response_model=IntegrationConnectionRead)
async def get_connection(
    connection_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> IntegrationConnectionRead:
    try:
        cid = UUID(connection_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid connection_id format") from None

    uow = UnitOfWork(db)
    service = ConnectionService(uow)
    conn = await service.get_connection(cid)
    if conn is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    if conn.user_id and conn.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Connection not found")
    if conn.runtime_id:
        await require_runtime_access(conn.runtime_id, current_user, db)

    return _to_read_dto(conn)


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connection(
    connection_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> None:
    try:
        cid = UUID(connection_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid connection_id format") from None

    uow = UnitOfWork(db)
    service = ConnectionService(uow)
    conn = await service.get_connection(cid)
    if conn is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    if conn.user_id and conn.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Connection not found")
    if conn.runtime_id:
        await require_runtime_access(conn.runtime_id, current_user, db)

    await service.revoke_connection(cid)
