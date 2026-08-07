from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.core.database import get_session
from app.models.users import User
from app.repositories import UnitOfWork
from app.schemas.oauth import (
    OAuthAuthorizeResponse,
    OAuthCallbackResponse,
    OAuthProviderRead,
    OAuthTokenExchangeRequest,
)
from app.services.oauth.service import OAuthService, OAuthState

router = APIRouter(prefix="/oauth", tags=["oauth"])


@router.get("/providers", response_model=list[OAuthProviderRead])
async def list_providers(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> list[OAuthProviderRead]:
    uow = UnitOfWork(db)
    service = OAuthService(uow)
    providers = await service.list_providers()
    return [OAuthProviderRead(**p) for p in providers]


@router.post("/authorize", response_model=OAuthAuthorizeResponse)
async def authorize(
    body: dict,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> OAuthAuthorizeResponse:
    provider = body.get("provider")
    project_id_raw = body.get("project_id")
    redirect_uri = body.get("redirect_uri")
    if not provider:
        raise HTTPException(status_code=400, detail="provider is required")
    project_id = uuid.UUID(project_id_raw) if project_id_raw else None
    uow = UnitOfWork(db)
    service = OAuthService(uow)
    result = await service.authorize(provider, current_user.id, project_id, redirect_uri)
    return OAuthAuthorizeResponse(url=result["url"], state=result["state"])


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
    result = await service.callback(state_obj.provider, code, state, state_obj.project_id)

    project_id = state_obj.project_id
    org_id = current_user.organization_id
    if project_id is None and org_id is not None:
        project = await uow.projects.get_by_organization(org_id)
        if project:
            project_id = project.id

    connection = await uow.providers.get_by_provider(
        str(project_id) if project_id else "",
        result["provider"],
    )
    if connection:
        await uow.providers.update(
            connection,
            status="active",
            display_name=result.get("display_name") or connection.display_name,
            config={**(connection.config or {}), "oauth_connection_id": result["connection_id"]},
        )
    elif project_id is not None:
        await uow.providers.create(
            organization_id=org_id,
            project_id=project_id,
            provider_name=result["provider"],
            display_name=result.get("display_name") or result["provider"],
            status="active",
            config={"oauth_connection_id": result["connection_id"]},
        )
    await uow.commit()

    return OAuthCallbackResponse(
        connection_id=result["connection_id"],
        provider=result["provider"],
        display_name=result["display_name"],
        scope=result["scope"],
    )


@router.post("/token", response_model=dict[str, Any])
async def exchange_token(
    body: OAuthTokenExchangeRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    uow = UnitOfWork(db)
    service = OAuthService(uow)
    project_id = uuid.UUID(body.project_id) if body.project_id else None
    result = await service.callback(body.provider, body.code, body.state, project_id)

    connection = await uow.providers.get_by_provider(
        str(project_id) if project_id else "",
        result["provider"],
    )
    if connection:
        await uow.providers.update(
            connection,
            status="active",
            display_name=result.get("display_name") or connection.display_name,
            config={**(connection.config or {}), "oauth_connection_id": result["connection_id"]},
        )
    elif project_id is not None:
        await uow.providers.create(
            organization_id=current_user.organization_id,
            project_id=project_id,
            provider_name=result["provider"],
            display_name=result.get("display_name") or result["provider"],
            status="active",
            config={"oauth_connection_id": result["connection_id"]},
        )
    await uow.commit()

    return result
