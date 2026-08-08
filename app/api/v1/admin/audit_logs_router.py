from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.constants import Permission
from app.admin.dependencies import AdminContext, require_permission
from app.admin.schemas import (
    AuditLogEntryRead,
    AuditLogSummaryRead,
)
from app.admin.services.audit_log import AuditLogService
from app.core.database import get_session

router = APIRouter(prefix="/admin", tags=["admin-audit-logs"])


@router.get("/audit-logs", response_model=list[AuditLogEntryRead])
async def admin_list_audit_logs(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    action: str | None = Query(default=None),
    admin_user_id: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    ctx: AdminContext = Depends(require_permission(Permission.AUDIT_READ)),
    db: AsyncSession = Depends(get_session),
) -> list[AuditLogEntryRead]:
    service = AuditLogService(db)
    date_from_dt = datetime.fromisoformat(date_from) if date_from else None
    date_to_dt = datetime.fromisoformat(date_to) if date_to else None
    logs = await service.log(
        admin_id="",
        action=action or "",
        resource_type="",
        limit=limit,
        offset=offset,
    )
    return [
        AuditLogEntryRead(
            id=str(log.id) if log.id else None,
            admin_user_id=str(log.admin_user_id) if log.admin_user_id else None,
            user_id=str(log.user_id) if log.user_id else None,
            action=log.action,
            resource_type=log.resource_type,
            resource_id=log.resource_id,
            previous_value=log.previous_value,
            new_value=log.new_value,
            ip_address=log.ip_address,
            user_agent=log.user_agent,
            reason=log.reason,
            success=log.success,
            created_at=log.created_at.isoformat() if log.created_at else "",
        )
        for log in logs
    ]


@router.get("/audit-logs/summary", response_model=AuditLogSummaryRead)
async def admin_audit_log_summary(
    ctx: AdminContext = Depends(require_permission(Permission.AUDIT_READ)),
    db: AsyncSession = Depends(get_session),
) -> AuditLogSummaryRead:
    return AuditLogSummaryRead(
        total_entries=0,
        actions={},
        top_admins=[],
    )