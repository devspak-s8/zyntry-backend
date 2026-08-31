from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.constants import Permission
from app.admin.dependencies import (
    AdminContext,
    require_permission,
    require_super_admin,
)
from app.admin.schemas import (
    AlertTimelineEvent,
    SecurityAlertAction,
    SecurityAlertRead,
)
from app.admin.services.security_actions import SecurityActionsService
from app.admin.services.audit_log import AuditLogService
from app.admin.services.security_engine import SecurityEngine
from app.admin.models import SecurityAlert
from app.core.database import get_session

router = APIRouter(prefix="/admin", tags=["admin-security"])


@router.get("/security/alerts", response_model=list[SecurityAlertRead])
async def admin_list_alerts(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None),
    risk_level: str | None = Query(default=None),
    alert_type: str | None = Query(default=None),
    min_score: int | None = Query(default=None),
    max_score: int | None = Query(default=None),
    ctx: AdminContext = Depends(require_permission(Permission.SECURITY_READ)),
    db: AsyncSession = Depends(get_session),
) -> list[SecurityAlertRead]:
    engine = SecurityEngine(db)
    alerts = await engine._alert_repo.list_all(
        limit=limit,
        offset=offset,
        status=status,
        risk_level=risk_level,
        alert_type=alert_type,
        min_score=min_score,
        max_score=max_score,
    )
    return [
        SecurityAlertRead(
            id=str(a.id) if a.id else None,
            alert_type=a.alert_type,
            risk_score=a.risk_score,
            risk_level=a.risk_level,
            status=a.status,
            title=a.title,
            description=a.description,
            ip_address=a.ip_address,
            country=a.country,
            asn=a.asn,
            user_id=str(a.user_id) if a.user_id else None,
            organization_id=str(a.organization_id) if a.organization_id else None,
            first_seen=a.first_seen.isoformat() if a.first_seen else "",
            last_seen=a.last_seen.isoformat() if a.last_seen else "",
            attempt_count=a.attempt_count,
            triggered_rules=a.triggered_rules,
            acknowledged_by=str(a.acknowledged_by) if a.acknowledged_by else None,
            resolved_at=a.resolved_at.isoformat() if a.resolved_at else None,
        )
        for a in alerts
    ]


@router.get("/security/alerts/summary")
async def admin_alert_summary(
    ctx: AdminContext = Depends(require_permission(Permission.SECURITY_READ)),
    db: AsyncSession = Depends(get_session),
) -> dict[str, int]:
    counts = await db.execute(
        select(SecurityAlert.status, SecurityAlert.risk_level, func.count(SecurityAlert.id))
        .group_by(SecurityAlert.status, SecurityAlert.risk_level)
    )
    total = open_count = critical = high = medium = low = 0
    for alert_status, risk_level, count in counts.all():
        count = int(count or 0)
        total += count
        if str(alert_status) == "open":
            open_count += count
        level = str(risk_level).lower()
        if level == "critical":
            critical += count
        elif level == "high":
            high += count
        elif level == "medium":
            medium += count
        elif level == "low":
            low += count
    return {
        "total_alerts": total,
        "open_alerts": open_count,
        "critical_alerts": critical,
        "high_alerts": high,
        "medium_alerts": medium,
        "low_alerts": low,
    }


@router.get("/security/alerts/{alert_id}", response_model=SecurityAlertRead)
async def admin_get_alert(
    alert_id: str,
    ctx: AdminContext = Depends(require_permission(Permission.SECURITY_READ)),
    db: AsyncSession = Depends(get_session),
) -> SecurityAlertRead:
    engine = SecurityEngine(db)
    alert = await engine._alert_repo.get_by_id(alert_id)
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
    return SecurityAlertRead(
        id=str(alert.id) if alert.id else None,
        alert_type=alert.alert_type,
        risk_score=alert.risk_score,
        risk_level=alert.risk_level,
        status=alert.status,
        title=alert.title,
        description=alert.description,
        ip_address=alert.ip_address,
        country=alert.country,
        asn=alert.asn,
        user_id=str(alert.user_id) if alert.user_id else None,
        organization_id=str(alert.organization_id) if alert.organization_id else None,
        first_seen=alert.first_seen.isoformat() if alert.first_seen else "",
        last_seen=alert.last_seen.isoformat() if alert.last_seen else "",
        attempt_count=alert.attempt_count,
        triggered_rules=alert.triggered_rules,
        acknowledged_by=str(alert.acknowledged_by) if alert.acknowledged_by else None,
        resolved_at=alert.resolved_at.isoformat() if alert.resolved_at else None,
    )


@router.post("/security/alerts/{alert_id}/action")
async def admin_alert_action(
    alert_id: str,
    body: SecurityAlertAction,
    ctx: AdminContext = Depends(require_permission(Permission.SECURITY_ACTIONS)),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    actions = SecurityActionsService(db)
    result = await actions.apply_action(alert_id, body.action, body.reason)
    if not result.get("success"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=result.get("error", "Action failed"))
    await AuditLogService(db).log_action(
        admin_user_id=str(ctx.admin_id),
        action=body.action,
        resource_type="security_alert" if body.action != "revoke_key" else "api_key",
        resource_id=alert_id,
        previous_value=None,
        new_value={"action": body.action},
        ip_address=None,
        user_agent=None,
        reason=body.reason,
    )
    await db.commit()
    return result


@router.get("/security/alerts/{alert_id}/timeline", response_model=list[AlertTimelineEvent])
async def admin_alert_timeline(
    alert_id: str,
    ctx: AdminContext = Depends(require_permission(Permission.SECURITY_READ)),
    db: AsyncSession = Depends(get_session),
) -> list[AlertTimelineEvent]:
    engine = SecurityEngine(db)
    timeline = await engine.get_alert_timeline(alert_id)
    return [AlertTimelineEvent(**e) for e in timeline]


@router.post("/security/scan")
async def admin_security_scan(
    ctx: AdminContext = Depends(require_super_admin),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    engine = SecurityEngine(db)
    return await engine.run_security_scan()
