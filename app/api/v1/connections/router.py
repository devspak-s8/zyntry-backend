from __future__ import annotations

import logging
from typing import Annotated, Any
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import _get_session_user, get_current_user
from app.api.v1.dependencies_tenant import require_runtime_access
from app.core.config import settings
from app.core.database import get_session
from app.core.errors import DomainError
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


def _oauth_error_redirect(integration_slug: str, code: str) -> RedirectResponse:
    query = urlencode({"connection_status": "error", "integration_slug": integration_slug, "error_code": code})
    return RedirectResponse(
        url=f"{settings.FRONTEND_URL.rstrip('/')}/console/integrations?{query}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> ConnectionAuthorizeResponse:
    if body.runtime_id:
        await require_runtime_access(body.runtime_id, current_user, db, project_id=body.project_id)
    uow = UnitOfWork(db)
    service = ConnectionService(uow)
    try:
        return await service.authorize(
            integration_slug=integration_slug.lower(),
            user_id=current_user.id,
            data=body,
        )
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.as_detail()) from exc
    except ValueError as exc:
        logger.warning("Invalid OAuth authorization request", extra={"integration_slug": integration_slug})
        raise HTTPException(
            status_code=400,
            detail={"code": "oauth_request_invalid", "message": "Review the integration settings and try again."},
        ) from exc


@router.get("/{integration_slug}/callback", response_model=None)
async def connection_callback(
    integration_slug: str,
    request: Request,
    code: Annotated[str, Query()] = "",
    state: Annotated[str, Query()] = "",
    error: Annotated[str, Query()] = "",
    error_description: Annotated[str, Query()] = "",
    # OAuth callbacks are provider redirects and may not include the browser
    # session cookie. The signed, expiring OAuth state binds the callback to
    # the initiating user; do not fail with a misleading "Not authenticated".
    current_user: User | None = Depends(_get_session_user),
    db: AsyncSession = Depends(get_session),
) -> Any:
    accepts_html = "text/html" in request.headers.get("accept", "")
    if error:
        # Providers report redirect mismatches and denials through the
        # callback query instead of returning an authorization code. Never
        # reflect provider details to the browser; expose a stable safe code.
        callback_code = "redirect_uri_mismatch" if error in {"redirect_uri_mismatch", "invalid_redirect_uri"} else "oauth_provider_denied"
        if accepts_html:
            return _oauth_error_redirect(integration_slug, callback_code)
        raise HTTPException(
            status_code=400,
            detail={"code": callback_code, "message": "The provider authorization was not completed. Try again."},
        )
    if not code or not state:
        if accepts_html:
            return _oauth_error_redirect(integration_slug, "oauth_callback_incomplete")
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
        runtime = await uow.runtimes.get(conn.runtime_id) if conn.runtime_id else None
        if current_user and runtime and runtime.project_id:
            try:
                await emit_integration_connection_updated(
                    str(current_user.id),
                    project_id=str(runtime.project_id),
                    provider=conn.integration_slug,
                    purpose="source",
                    oauth_connection_id=str(conn.id),
                    tool_id=None,
                    source_id=None,
                )
            except Exception:
                pass
        result = _to_read_dto(conn)
        accepts_html = "text/html" in request.headers.get("accept", "")
        if accepts_html:
            project_id = str(runtime.project_id) if runtime and runtime.project_id else ""
            callback_query = (
                f"connection_status=success&integration_slug={conn.integration_slug}"
                f"&runtime_id={conn.runtime_id or ''}&project_id={project_id}"
            )
            callback_path = (
                f"/console/projects/{project_id}/integrations"
                if project_id
                else "/console/integrations"
            )
            return RedirectResponse(
                url=f"{settings.FRONTEND_URL.rstrip('/')}{callback_path}?{callback_query}",
                status_code=status.HTTP_303_SEE_OTHER,
            )
        return result
    except DomainError as exc:
        if accepts_html:
            return _oauth_error_redirect(integration_slug, exc.code)
        raise HTTPException(status_code=exc.status_code, detail=exc.as_detail()) from exc
    except ValueError as exc:
        logger.warning("OAuth callback failed", extra={"integration_slug": integration_slug})
        callback_code = "redirect_uri_mismatch" if "redirect_uri" in str(exc).lower() else "oauth_callback_failed"
        if accepts_html:
            return _oauth_error_redirect(integration_slug, callback_code)
        raise HTTPException(
            status_code=400,
            detail={"code": callback_code, "message": "The provider authorization could not be completed. Try again."},
        ) from exc


@router.post("", response_model=IntegrationConnectionRead, status_code=status.HTTP_201_CREATED)
async def create_direct_connection(
    body: ConnectionDirectCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> IntegrationConnectionRead:
    if body.runtime_id:
        await require_runtime_access(body.runtime_id, current_user, db, project_id=body.project_id)
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
    current_user: User = Depends(get_current_user),
    runtime_id: Annotated[str | None, Query()] = None,
    project_id: Annotated[str | None, Query()] = None,
    end_user_id: Annotated[str | None, Query()] = None,
    integration_slug: Annotated[str | None, Query()] = None,
    connection_mode: Annotated[str | None, Query()] = None,
    db: AsyncSession = Depends(get_session),
) -> list[IntegrationConnectionRead]:
    if runtime_id:
        await require_runtime_access(runtime_id, current_user, db, project_id=project_id)
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
    current_user: User = Depends(get_current_user),
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
    current_user: User = Depends(get_current_user),
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
