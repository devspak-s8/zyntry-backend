from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.constants import Permission
from app.admin.dependencies import AdminContext, require_permission
from app.admin.services.audit_log import AuditLogService
from app.core.database import get_session
from app.models.apikeys import ApiKey
from app.schemas.apikeys import ApiKeyRead

router = APIRouter(prefix="/admin", tags=["admin-api-keys"])


@router.get("/api-keys", response_model=list[ApiKeyRead])
async def admin_list_api_keys(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    revoked: bool | None = Query(default=None),
    runtime_id: str | None = Query(default=None),
    ctx: AdminContext = Depends(require_permission(Permission.SECURITY_READ)),
    db: AsyncSession = Depends(get_session),
) -> list[ApiKeyRead]:
    stmt = select(ApiKey).order_by(desc(ApiKey.created_at)).offset(offset).limit(limit)
    if revoked is not None:
        stmt = stmt.where(ApiKey.revoked == revoked)
    if runtime_id:
        try:
            runtime_uuid = uuid.UUID(runtime_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid runtime id") from exc
        stmt = stmt.where(ApiKey.runtime_id == runtime_uuid)
    result = await db.execute(stmt)
    return [ApiKeyRead.model_validate(key) for key in result.scalars().all()]


@router.post("/api-keys/{key_id}/revoke")
async def admin_revoke_api_key(
    key_id: str,
    ctx: AdminContext = Depends(require_permission(Permission.SECURITY_ACTIONS)),
    db: AsyncSession = Depends(get_session),
) -> dict[str, str | bool]:
    try:
        key_uuid = uuid.UUID(key_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid api key id") from exc
    key = await db.get(ApiKey, key_uuid)
    if key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
    key.revoked = True
    await AuditLogService(db).log_action(
        admin_user_id=str(ctx.admin_id),
        action="revoke_api_key",
        resource_type="api_key",
        resource_id=key_id,
        previous_value={"revoked": False},
        new_value={"revoked": True},
        ip_address=None,
        user_agent=None,
        reason="Revoked from admin console",
        user_id=str(key.user_id) if key.user_id else None,
    )
    await db.commit()
    return {"success": True, "message": "API key revoked"}
