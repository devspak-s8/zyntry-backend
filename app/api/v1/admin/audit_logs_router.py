from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.constants import Permission
from app.admin.dependencies import AdminContext, require_permission
from app.admin.schemas import (
    AuditLogEntryRead,
    AuditLogSummaryRead,
)
from app.admin.services.audit_log import AuditLogService
from app.core.database import get_session
from app.admin.models import AdminAuditLog

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
    stmt = select(AdminAuditLog).order_by(desc(AdminAuditLog.created_at)).offset(offset).limit(limit)
    if action:
        stmt = stmt.where(AdminAuditLog.action == action)
    if admin_user_id:
        stmt = stmt.where(AdminAuditLog.admin_user_id == admin_user_id)
    if date_from:
        try:
            stmt = stmt.where(AdminAuditLog.created_at >= datetime.fromisoformat(date_from.replace("Z", "+00:00")))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid date_from") from exc
    if date_to:
        try:
            stmt = stmt.where(AdminAuditLog.created_at <= datetime.fromisoformat(date_to.replace("Z", "+00:00")))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid date_to") from exc
    result = await db.execute(stmt)
    logs = result.scalars().all()
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
    total = await db.scalar(select(func.count()).select_from(AdminAuditLog)) or 0
    action_rows = await db.execute(select(AdminAuditLog.action, func.count()).group_by(AdminAuditLog.action))
    actions = {str(row[0]): int(row[1]) for row in action_rows.all()}
    admin_rows = await db.execute(select(AdminAuditLog.admin_user_id, func.count()).where(AdminAuditLog.admin_user_id.is_not(None)).group_by(AdminAuditLog.admin_user_id).order_by(func.count().desc()).limit(10))
    top_admins = [{"admin_user_id": str(row[0]), "entries": int(row[1])} for row in admin_rows.all()]
    return AuditLogSummaryRead(total_entries=int(total), actions=actions, top_admins=top_admins)
