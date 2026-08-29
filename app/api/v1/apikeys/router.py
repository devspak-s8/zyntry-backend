from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.api.v1.dependencies_tenant import require_api_key_access, require_project_membership
from app.core.database import get_session
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
    runtime_id: Annotated[str | None, Query()] = None,
    db: AsyncSession = Depends(get_session),
) -> list[ApiKeyRead]:
    if project_id is not None:
        await require_project_membership(project_id, current_user, db)
    if runtime_id is not None:
        from app.api.v1.dependencies_tenant import require_runtime_access
        await require_runtime_access(runtime_id, current_user, db)
    service = ApiKeyService(db)
    keys = await service.list_keys(
        project_id=project_id,
        user_id=current_user.id,
        runtime_id=runtime_id,
    )
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

    key = await require_api_key_access(kid, current_user, db)

    return ApiKeyRead(
        id=key.id,
        name=key.name,
        prefix=key.prefix,
        runtime_id=getattr(key, "runtime_id", None),
        environment=getattr(key, "environment", "development"),
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
    runtime = None

    if proj_id is not None:
        try:
            pid = uuid.UUID(str(proj_id))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid project id")
        proj = await db.get(Project, pid)
        if proj is None:
            raise HTTPException(status_code=404, detail="Project not found")
        if proj.organization_id != current_user.organization_id and not current_user.is_superuser:
            raise HTTPException(status_code=403, detail="Cannot create an API key for another organization")
        org_id = proj.organization_id

    if body.runtime_id is not None:
        from app.api.v1.dependencies_tenant import require_runtime_access

        runtime = await require_runtime_access(body.runtime_id, current_user, db)
        if runtime.project_id is not None:
            if proj_id is not None and runtime.project_id != uuid.UUID(str(proj_id)):
                raise HTTPException(
                    status_code=400,
                    detail="Runtime does not belong to the selected project",
                )
            if proj_id is None:
                proj_id = runtime.project_id
        if runtime.organization_id is not None:
            org_id = runtime.organization_id
        body = body.model_copy(
            update={"environment": runtime.environment or "development"}
        )

    if proj_id is not None and body.project_id != proj_id:
        body = body.model_copy(update={"project_id": proj_id})

    service = ApiKeyService(db)
    try:
        result = await service.create_key(
            user_id=current_user.id,
            data=body,
            organization_id=org_id,
        )
    except Exception as exc:
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
        **result["api_key"].model_dump(),
        key=result["raw_key"],
    )


@router.post("/{key_id}/rotate", response_model=ApiKeyRotateResponse)
@router.put("/{key_id}/rotate", response_model=ApiKeyRotateResponse)
async def rotate_api_key(
    key_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> ApiKeyRotateResponse:
    service = ApiKeyService(db)
    try:
        await require_api_key_access(key_id, current_user, db)
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

    key = await require_api_key_access(kid, current_user, db)

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
        runtime_id=getattr(key, "runtime_id", None),
        environment=getattr(key, "environment", "development"),
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
        await require_api_key_access(key_id, current_user, db)
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

    key = await require_api_key_access(kid, current_user, db)

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
        await require_api_key_access(key_id, current_user, db)
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
        await require_api_key_access(key_id, current_user, db)
        result = await service.update_scopes(key_id, body.scopes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return ApiKeyRead(**result)
