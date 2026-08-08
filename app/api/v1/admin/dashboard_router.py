from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.constants import Permission
from app.admin.dependencies import require_permission
from app.admin.schemas import (
    DashboardLiveMetricsRead,
    DashboardMetricsRead,
    SecurityAlertRead,
)
from app.admin.services.dashboard import DashboardService
from app.core.database import get_session

router = APIRouter(prefix="/admin", tags=["admin-dashboard"])


@router.get("/metrics", response_model=DashboardMetricsRead)
async def admin_dashboard_metrics(
    ctx: Any = Depends(require_permission(Permission.DASHBOARD_READ)),
    db: AsyncSession = Depends(get_session),
) -> DashboardMetricsRead:
    service = DashboardService(db)
    metrics = await service.get_metrics()
    return DashboardMetricsRead(**metrics)


@router.get("/metrics/live", response_model=DashboardLiveMetricsRead)
async def admin_dashboard_live_metrics(
    ctx: Any = Depends(require_permission(Permission.DASHBOARD_LIVE)),
    db: AsyncSession = Depends(get_session),
) -> DashboardLiveMetricsRead:
    service = DashboardService(db)
    metrics = await service.get_live_metrics()
    return DashboardLiveMetricsRead(**metrics)


@router.get("/alerts/recent", response_model=list[SecurityAlertRead])
async def admin_recent_alerts(
    limit: int = Query(default=10, ge=1, le=50),
    ctx: Any = Depends(require_permission(Permission.SECURITY_READ)),
    db: AsyncSession = Depends(get_session),
) -> list[SecurityAlertRead]:
    service = DashboardService(db)
    alerts = await service.get_recent_alerts(limit=limit)
    return [SecurityAlertRead(**a) for a in alerts]


@router.get("/alerts/open-count", response_model=dict[str, int])
async def admin_open_alert_count(
    ctx: Any = Depends(require_permission(Permission.SECURITY_READ)),
    db: AsyncSession = Depends(get_session),
) -> dict[str, int]:
    service = DashboardService(db)
    count = await service.get_open_alert_count()
    return {"open_alerts": count}