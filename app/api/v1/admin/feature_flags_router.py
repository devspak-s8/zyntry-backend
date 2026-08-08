from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.constants import Permission
from app.admin.dependencies import AdminContext, require_permission
from app.admin.schemas import (
    FeatureFlagCreate,
    FeatureFlagRead,
    FeatureFlagUpdate,
)
from app.admin.services.feature_flags import FeatureFlagService
from app.core.database import get_session

router = APIRouter(prefix="/admin", tags=["admin-feature-flags"])


@router.get("/feature-flags", response_model=list[FeatureFlagRead])
async def admin_list_feature_flags(
    scope: str | None = Query(default=None),
    enabled_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    ctx: AdminContext = Depends(require_permission(Permission.FEATURE_FLAGS_READ)),
    db: AsyncSession = Depends(get_session),
) -> list[FeatureFlagRead]:
    service = FeatureFlagService(db)
    flags = await service.list_all(scope=scope, enabled_only=enabled_only, limit=limit, offset=offset)
    return [
        FeatureFlagRead(
            id=str(f.id) if f.id else None,
            key=f.key,
            name=f.name,
            description=f.description,
            scope=f.scope,
            flag_type=f.flag_type,
            enabled=f.enabled,
            default_value=f.default_value,
            rollout_percentage=f.rollout_percentage,
            allowlist=f.allowlist,
            is_system=f.is_system,
            updated_by=str(f.updated_by) if f.updated_by else None,
        )
        for f in flags
    ]


@router.get("/feature-flags/{key}", response_model=FeatureFlagRead)
async def admin_get_feature_flag(
    key: str,
    ctx: AdminContext = Depends(require_permission(Permission.FEATURE_FLAGS_READ)),
    db: AsyncSession = Depends(get_session),
) -> FeatureFlagRead:
    service = FeatureFlagService(db)
    flag = await service.get_by_key(key)
    if flag is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feature flag not found")
    return FeatureFlagRead(
        id=str(flag.id) if flag.id else None,
        key=flag.key,
        name=flag.name,
        description=flag.description,
        scope=flag.scope,
        flag_type=flag.flag_type,
        enabled=flag.enabled,
        default_value=flag.default_value,
        rollout_percentage=flag.rollout_percentage,
        allowlist=flag.allowlist,
        is_system=flag.is_system,
        updated_by=str(flag.updated_by) if flag.updated_by else None,
    )


@router.post("/feature-flags")
async def admin_create_feature_flag(
    body: FeatureFlagCreate,
    ctx: AdminContext = Depends(require_permission(Permission.FEATURE_FLAGS_WRITE)),
    db: AsyncSession = Depends(get_session),
) -> FeatureFlagRead:
    service = FeatureFlagService(db)
    flag = await service.create_flag(
        key=body.key,
        name=body.name,
        description=body.description,
        scope=body.scope,
        flag_type=body.flag_type,
        enabled=body.enabled,
        default_value=body.default_value,
        rollout_percentage=body.rollout_percentage,
        allowlist=body.allowlist,
    )
    return FeatureFlagRead(
        id=str(flag.id) if flag.id else None,
        key=flag.key,
        name=flag.name,
        description=flag.description,
        scope=flag.scope,
        flag_type=flag.flag_type,
        enabled=flag.enabled,
        default_value=flag.default_value,
        rollout_percentage=flag.rollout_percentage,
        allowlist=flag.allowlist,
        is_system=flag.is_system,
        updated_by=None,
    )


@router.put("/feature-flags/{key}")
async def admin_update_feature_flag(
    key: str,
    body: FeatureFlagUpdate,
    ctx: AdminContext = Depends(require_permission(Permission.FEATURE_FLAGS_WRITE)),
    db: AsyncSession = Depends(get_session),
) -> FeatureFlagRead:
    service = FeatureFlagService(db)
    flag = await service.update_flag(key, **body.model_dump(exclude_unset=True))
    if flag is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feature flag not found")
    return FeatureFlagRead(
        id=str(flag.id) if flag.id else None,
        key=flag.key,
        name=flag.name,
        description=flag.description,
        scope=flag.scope,
        flag_type=flag.flag_type,
        enabled=flag.enabled,
        default_value=flag.default_value,
        rollout_percentage=flag.rollout_percentage,
        allowlist=flag.allowlist,
        is_system=flag.is_system,
        updated_by=None,
    )


@router.post("/feature-flags/{key}/enable")
async def admin_enable_feature_flag(
    key: str,
    ctx: AdminContext = Depends(require_permission(Permission.FEATURE_FLAGS_WRITE)),
    db: AsyncSession = Depends(get_session),
) -> FeatureFlagRead:
    service = FeatureFlagService(db)
    flag = await service.enable_flag(key)
    if flag is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feature flag not found")
    return FeatureFlagRead(
        id=str(flag.id) if flag.id else None,
        key=flag.key,
        name=flag.name,
        description=flag.description,
        scope=flag.scope,
        flag_type=flag.flag_type,
        enabled=flag.enabled,
        default_value=flag.default_value,
        rollout_percentage=flag.rollout_percentage,
        allowlist=flag.allowlist,
        is_system=flag.is_system,
        updated_by=None,
    )


@router.post("/feature-flags/{key}/disable")
async def admin_disable_feature_flag(
    key: str,
    ctx: AdminContext = Depends(require_permission(Permission.FEATURE_FLAGS_WRITE)),
    db: AsyncSession = Depends(get_session),
) -> FeatureFlagRead:
    service = FeatureFlagService(db)
    flag = await service.disable_flag(key)
    if flag is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feature flag not found")
    return FeatureFlagRead(
        id=str(flag.id) if flag.id else None,
        key=flag.key,
        name=flag.name,
        description=flag.description,
        scope=flag.scope,
        flag_type=flag.flag_type,
        enabled=flag.enabled,
        default_value=flag.default_value,
        rollout_percentage=flag.rollout_percentage,
        allowlist=flag.allowlist,
        is_system=flag.is_system,
        updated_by=None,
    )