from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any
from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.api.v1.dependencies_tenant import require_project_membership
from app.api.v1.features.dependencies import require_feature
from app.core.database import get_session
from app.core.config import settings
from app.core.ws_events import emit_integration_connection_updated
from app.models.users import User
from app.repositories import UnitOfWork
from app.schemas.oauth import (
    OAuthAuthorizeRequest,
    OAuthAuthorizeResponse,
    OAuthCallbackResponse,
    OAuthProviderRead,
    OAuthTokenExchangeRequest,
)
from app.services.integrations import IntegrationService
from app.services.oauth.service import OAuthError, OAuthService, OAuthState

router = APIRouter(prefix="/oauth", tags=["oauth"])
logger = logging.getLogger(__name__)
TOOLS_GUARD = [Depends(require_feature("tools_connectors"))]


def _validate_frontend_redirect(redirect_uri: str | None) -> None:
    if redirect_uri is None:
        return
    parsed = urlparse(redirect_uri)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not (
        hostname == "localhost"
        or hostname == "zyntry.space"
        or hostname.endswith(".zyntry.space")
    ):
        raise HTTPException(status_code=400, detail="Invalid OAuth redirect URI")


async def _materialize_integration(
    uow: UnitOfWork,
    result: dict[str, Any],
    project_id: uuid.UUID,
    purpose: str,
    display_name: str | None = None,
    source_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return await IntegrationService(uow).materialize_oauth_connection(
        provider=result["provider"],
        project_id=str(project_id),
        display_name=display_name or result.get("display_name") or result["provider"],
        oauth_connection_id=result["connection_id"],
        purpose=purpose,
        source_config=source_config,
    )


async def _emit_integration_result(user_id: str, result: dict[str, Any]) -> None:
    await emit_integration_connection_updated(user_id, **result)


@router.get("/providers", response_model=list[OAuthProviderRead], dependencies=TOOLS_GUARD)
async def list_providers(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> list[OAuthProviderRead]:
    uow = UnitOfWork(db)
    service = OAuthService(uow)
    providers = await service.list_providers()
    return [OAuthProviderRead(**p) for p in providers]


@router.post("/authorize", response_model=OAuthAuthorizeResponse, dependencies=TOOLS_GUARD)
async def authorize(
    body: OAuthAuthorizeRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> OAuthAuthorizeResponse:
    try:
        project_id = uuid.UUID(body.project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project_id") from None
    await require_project_membership(str(project_id), current_user, db)
    _validate_frontend_redirect(body.redirect_uri)
    uow = UnitOfWork(db)
    service = OAuthService(uow)
    existing = await service.get_connection_by_project(project_id, body.provider)
    if existing is not None and existing.expires_at is not None:
        expires_at = existing.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at <= datetime.now(UTC):
            try:
                await service.refresh_token(existing.id)
            except OAuthError:
                existing = None
    if existing is not None:
        user_info = (existing.metadata_ or {}).get("user_info", {})
        display_name = (
            body.display_name
            or user_info.get("name")
            or user_info.get("email")
            or body.provider
        )
        integration = await _materialize_integration(
            uow,
            {
                "provider": body.provider,
                "connection_id": str(existing.id),
                "display_name": display_name,
            },
            project_id,
            body.purpose,
            display_name,
            body.source_config,
        )
        await _emit_integration_result(str(current_user.id), integration)
        return OAuthAuthorizeResponse(
            requires_authorization=False,
            **integration,
        )
    try:
        result = await service.authorize(
            body.provider,
            current_user.id,
            project_id,
            body.redirect_uri,
            body.purpose,
            body.display_name,
            body.source_config,
        )
    except OAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return OAuthAuthorizeResponse(
        requires_authorization=True,
        url=result["url"],
        state=result["state"],
        provider=body.provider,
        purpose=body.purpose,
    )


@router.get("/callback", response_model=OAuthCallbackResponse)
async def callback(
    current_user: Annotated[User, Depends(get_current_user)],
    code: Annotated[str, Query()] = "",
    state: Annotated[str, Query()] = "",
    db: AsyncSession = Depends(get_session),
) -> OAuthCallbackResponse:
    db_result = await db.execute(
        select(OAuthState).where(
            OAuthState.state == state,
            OAuthState.expires_at > datetime.now(UTC),
        )
    )
    state_obj = db_result.scalar_one_or_none()
    if state_obj is None:
        raise HTTPException(status_code=400, detail="Invalid or expired state")
    uow = UnitOfWork(db)
    service = OAuthService(uow)
    try:
        result = await service.callback(
            state_obj.provider,
            code,
            state,
            state_obj.project_id,
            expected_user_id=current_user.id,
        )
    except OAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    project_id = state_obj.project_id
    if project_id is None and current_user.organization_id is not None:
        project = await uow.projects.get_by_organization(current_user.organization_id)
        if project:
            project_id = project.id
    if project_id is None:
        raise HTTPException(status_code=400, detail="OAuth project is required")
    integration = await _materialize_integration(uow, result, project_id, "tool")
    await _emit_integration_result(str(current_user.id), integration)

    return OAuthCallbackResponse(
        connection_id=result["connection_id"],
        provider=result["provider"],
        display_name=result["display_name"],
        scope=result["scope"],
    )


@router.get("/{provider}/callback", response_class=RedirectResponse)
async def provider_callback(
    provider: str,
    code: Annotated[str, Query()] = "",
    state: Annotated[str, Query()] = "",
    error: Annotated[str, Query()] = "",
    error_description: Annotated[str, Query()] = "",
    db: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    db_result = await db.execute(
        select(OAuthState).where(
            OAuthState.state == state,
            OAuthState.provider == provider.lower(),
            OAuthState.expires_at > datetime.now(UTC),
        )
    )
    state_obj = db_result.scalar_one_or_none()
    if state_obj is None:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

    frontend_callback = f"{settings.FRONTEND_URL.rstrip('/')}/oauth/callback"
    if error:
        query = urlencode({"status": "error", "provider": provider.lower(), "error": error_description or error})
        return RedirectResponse(f"{frontend_callback}?{query}", status_code=302)
    if not code or state_obj.project_id is None or state_obj.user_id is None:
        raise HTTPException(status_code=400, detail="Incomplete OAuth callback")

    project_id = state_obj.project_id
    user_id = state_obj.user_id
    purpose = state_obj.purpose
    display_name = state_obj.display_name
    source_config = dict(state_obj.source_config or {})
    uow = UnitOfWork(db)
    service = OAuthService(uow)
    try:
        result = await service.callback(
            provider.lower(), code, state, project_id,
            expected_user_id=user_id,
        )
        integration = await _materialize_integration(
            uow, result, project_id, purpose, display_name, source_config,
        )
        await _emit_integration_result(str(user_id), integration)
    except (OAuthError, ValueError) as exc:
        await db.rollback()
        query = urlencode({"status": "error", "provider": provider.lower(), "error": str(exc)})
        return RedirectResponse(f"{frontend_callback}?{query}", status_code=302)
    except Exception:
        await db.rollback()
        logger.exception("OAuth callback failed for provider %s", provider)
        query = urlencode({
            "status": "error",
            "provider": provider.lower(),
            "error": "Unable to complete the connection. Please try again.",
        })
        return RedirectResponse(f"{frontend_callback}?{query}", status_code=302)

    query = urlencode({
        "status": "success", "provider": provider.lower(),
        "project_id": str(project_id),
        "purpose": integration["purpose"],
        "tool_id": integration.get("tool_id") or "",
        "source_id": integration.get("source_id") or "",
    })
    return RedirectResponse(f"{frontend_callback}?{query}", status_code=302)


@router.post("/token", response_model=dict[str, Any], dependencies=TOOLS_GUARD)
async def exchange_token(
    body: OAuthTokenExchangeRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    uow = UnitOfWork(db)
    service = OAuthService(uow)
    try:
        project_id = uuid.UUID(body.project_id) if body.project_id else None
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project_id") from None
    if project_id is None:
        raise HTTPException(status_code=400, detail="project_id is required")
    await require_project_membership(str(project_id), current_user, db)
    try:
        result = await service.callback(
            body.provider,
            body.code,
            body.state,
            project_id,
            expected_user_id=current_user.id,
        )
    except OAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    integration = await _materialize_integration(
        uow,
        result,
        project_id,
        body.purpose,
        body.display_name,
        body.source_config,
    )
    await _emit_integration_result(str(current_user.id), integration)

    return {**result, **integration}
