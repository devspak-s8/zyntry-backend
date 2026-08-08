from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.core.database import get_session
from app.core.security import generate_api_key, hash_token
from app.events import NotificationEvent
from app.models.apikeys import ApiKey
from app.models.projects import Project
from app.models.users import User
from app.repositories import UnitOfWork
from app.schemas.apikeys import (
    ApiKeyCreate,
    ApiKeyCreateResponse,
    ApiKeyExpireRequest,
    ApiKeyRead,
    ApiKeyRotateResponse,
    ApiKeyScopeUpdate,
    ApiKeyUsageResponse,
)
from app.services.apikeys import ApiKeyService
from app.services.notifications import enqueue_notification

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/apikeys", tags=["apikeys"])


@router.get("", response_model=list[ApiKeyRead])
async def list_api_keys(
    current_user: Annotated[User, Depends(get_current_user)],
    project_id: Annotated[str | None, Query()] = None,
    db: AsyncSession = Depends(get_session),
) -> list[ApiKeyRead]:
    service = ApiKeyService(db)
    keys = await service.list_keys(project_id=project_id)
    return [ApiKeyRead(**k) for k in keys]


@router.get("/{key_id}", response_model=ApiKeyRead)
async def get_api_key(
    key_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> ApiKeyRead:
    import uuid

    try:
        kid = uuid.UUID(key_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid api key id")

    key = await db.get(ApiKey, kid)
    if key is None:
        raise HTTPException(status_code=404, detail="API key not found")

    return ApiKeyRead(
        id=key.id,
        name=key.name,
        prefix=key.prefix,
        scopes=key.scopes,
        revoked=key.revoked,
        expires_at=key.expires_at,
        last_used_at=key.last_used_at,
        usage_count=key.usage_count,
        usage_stats=key.usage_stats,
        created_at=key.created_at,
        updated_at=key.updated_at,
    )


@router.post("", response_model=ApiKeyCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    body: ApiKeyCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> ApiKeyCreateResponse:
    import uuid

    org_id = current_user.organization_id
    proj_id = body.project_id

    if proj_id is not None:
        try:
            pid = uuid.UUID(str(proj_id))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid project id")
        proj = await db.get(Project, pid)
        if proj is None:
            raise HTTPException(status_code=404, detail="Project not found")
        if org_id is None:
            org_id = proj.organization_id

    if org_id is None:
        raise HTTPException(
            status_code=400,
            detail="User must belong to an organization or provide a project_id",
        )

    raw_key = generate_api_key("sk_live")
    uow = UnitOfWork(db)
    try:
        key = await uow.api_keys.create(
            name=body.name,
            hashed_key=hash_token(raw_key),
            prefix=raw_key[:16],
            organization_id=org_id,
            user_id=current_user.id,
            project_id=proj_id,
            scopes=body.scopes,
        )
        await uow.commit()
    except Exception as exc:
        await uow.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to create API key: {exc}")

    try:
        event = NotificationEvent(
            event_type="api_key.created",
            recipient=current_user.email,
            data={"key_name": body.name},
            category="security",
            sender_name="Zyntry Security",
            sender_email="security@zyntry.space",
        )
        enqueue_notification(event)
    except Exception:
        logger.exception("Failed to enqueue API key created email")

    return ApiKeyCreateResponse(
        id=key.id,
        name=key.name,
        prefix=key.prefix,
        scopes=key.scopes,
        revoked=key.revoked,
        expires_at=key.expires_at,
        last_used_at=key.last_used_at,
        usage_count=key.usage_count,
        usage_stats=key.usage_stats,
        created_at=key.created_at,
        updated_at=key.updated_at,
        key=raw_key,
    )


@router.put("/{key_id}/rotate", response_model=ApiKeyRotateResponse)
async def rotate_api_key(
    key_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> ApiKeyRotateResponse:
    service = ApiKeyService(db)
    try:
        result = await service.rotate_key(key_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        event = NotificationEvent(
            event_type="api_key.rotated",
            recipient=current_user.email,
            data={"key_name": result.get("name", "API Key")},
            category="security",
            sender_name="Zyntry Security",
            sender_email="security@zyntry.space",
        )
        enqueue_notification(event)
    except Exception:
        logger.exception("Failed to enqueue API key rotated email")

    return ApiKeyRotateResponse(
        api_key=result["api_key"],
        raw_key=result["raw_key"],
    )


@router.post("/{key_id}/expire", response_model=ApiKeyRead)
async def expire_api_key(
    key_id: str,
    body: ApiKeyExpireRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> ApiKeyRead:
    import uuid

    try:
        kid = uuid.UUID(key_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid api key id")

    key = await db.get(ApiKey, kid)
    if key is None:
        raise HTTPException(status_code=404, detail="API key not found")

    uow = UnitOfWork(db)
    try:
        await uow.api_keys.update(key, expires_at=body.expires_at)
        await uow.commit()
    except Exception as exc:
        await uow.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to expire API key: {exc}")

    return ApiKeyRead(
        id=key.id,
        name=key.name,
        prefix=key.prefix,
        scopes=key.scopes,
        revoked=key.revoked,
        expires_at=key.expires_at,
        last_used_at=key.last_used_at,
        usage_count=key.usage_count,
        usage_stats=key.usage_stats,
        created_at=key.created_at,
        updated_at=key.updated_at,
    )


@router.post("/{key_id}/revoke", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    key_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> None:
    service = ApiKeyService(db)
    try:
        key = await service.revoke_key(key_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        event = NotificationEvent(
            event_type="api_key.revoked",
            recipient=current_user.email,
            data={"key_name": key.get("name", "API Key")},
            category="security",
            sender_name="Zyntry Security",
            sender_email="security@zyntry.space",
        )
        enqueue_notification(event)
    except Exception:
        logger.exception("Failed to enqueue API key revoked email")


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_api_key(
    key_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> None:
    import uuid

    try:
        kid = uuid.UUID(key_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid api key id")

    key = await db.get(ApiKey, kid)
    if key is None:
        raise HTTPException(status_code=404, detail="API key not found")

    uow = UnitOfWork(db)
    try:
        await uow.api_keys.delete(key)
        await uow.commit()
    except Exception as exc:
        await uow.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete API key: {exc}")


@router.get("/{key_id}/usage", response_model=ApiKeyUsageResponse)
async def get_api_key_usage(
    key_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> ApiKeyUsageResponse:
    service = ApiKeyService(db)
    try:
        result = await service.get_usage(key_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return ApiKeyUsageResponse(**result)


@router.put("/{key_id}/scopes", response_model=ApiKeyRead)
async def update_api_key_scopes(
    key_id: str,
    body: ApiKeyScopeUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> ApiKeyRead:
    service = ApiKeyService(db)
    try:
        result = await service.update_scopes(key_id, body.scopes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return ApiKeyRead(**result)
