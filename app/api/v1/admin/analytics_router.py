from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.constants import Permission
from app.admin.dependencies import AdminContext, require_permission
from app.admin.schemas import (
    AnalyticsOverviewRead,
    AnalyticsSummaryRead,
)
from app.admin.services.usage_analytics import UsageAnalyticsService
from app.core.database import get_session

router = APIRouter(prefix="/admin", tags=["admin-analytics"])


@router.get("/analytics", response_model=AnalyticsOverviewRead)
async def admin_analytics_overview(
    hours: int = Query(default=24, ge=1, le=168),
    ctx: AdminContext = Depends(require_permission(Permission.USAGE_READ)),
    db: AsyncSession = Depends(get_session),
) -> AnalyticsOverviewRead:
    service = UsageAnalyticsService(db)
    overview = await service.get_overview(hours=hours)
    return AnalyticsOverviewRead(**overview)


@router.get("/analytics/top/organizations", response_model=list[dict[str, Any]])
async def admin_top_organizations(
    hours: int = Query(default=24, ge=1, le=168),
    limit: int = Query(default=10, ge=1, le=50),
    ctx: AdminContext = Depends(require_permission(Permission.USAGE_READ)),
    db: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    service = UsageAnalyticsService(db)
    overview = await service.get_overview(hours=hours)
    return overview["top_organizations"][:limit]


@router.get("/analytics/top/users", response_model=list[dict[str, Any]])
async def admin_top_users(
    hours: int = Query(default=24, ge=1, le=168),
    limit: int = Query(default=10, ge=1, le=50),
    ctx: AdminContext = Depends(require_permission(Permission.USAGE_READ)),
    db: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    service = UsageAnalyticsService(db)
    overview = await service.get_overview(hours=hours)
    return overview["top_users"][:limit]


@router.get("/analytics/top/models", response_model=list[dict[str, Any]])
async def admin_top_models(
    hours: int = Query(default=24, ge=1, le=168),
    limit: int = Query(default=10, ge=1, le=50),
    ctx: AdminContext = Depends(require_permission(Permission.USAGE_READ)),
    db: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    service = UsageAnalyticsService(db)
    overview = await service.get_overview(hours=hours)
    return overview["top_models"][:limit]


@router.get("/analytics/top/providers", response_model=list[dict[str, Any]])
async def admin_top_providers(
    hours: int = Query(default=24, ge=1, le=168),
    limit: int = Query(default=10, ge=1, le=50),
    ctx: AdminContext = Depends(require_permission(Permission.USAGE_READ)),
    db: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    service = UsageAnalyticsService(db)
    overview = await service.get_overview(hours=hours)
    return overview["top_providers"][:limit]


@router.get("/analytics/top/runtimes", response_model=list[dict[str, Any]])
async def admin_top_runtimes(
    hours: int = Query(default=24, ge=1, le=168),
    limit: int = Query(default=10, ge=1, le=50),
    ctx: AdminContext = Depends(require_permission(Permission.USAGE_READ)),
    db: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    service = UsageAnalyticsService(db)
    overview = await service.get_overview(hours=hours)
    return overview["top_runtimes"][:limit]


@router.get("/analytics/top/tools", response_model=list[dict[str, Any]])
async def admin_top_tools(
    hours: int = Query(default=24, ge=1, le=168),
    limit: int = Query(default=10, ge=1, le=50),
    ctx: AdminContext = Depends(require_permission(Permission.USAGE_READ)),
    db: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    service = UsageAnalyticsService(db)
    overview = await service.get_overview(hours=hours)
    return overview["top_tools"][:limit]


@router.get("/analytics/top/endpoints", response_model=list[dict[str, Any]])
async def admin_top_endpoints(
    hours: int = Query(default=24, ge=1, le=168),
    limit: int = Query(default=10, ge=1, le=50),
    ctx: AdminContext = Depends(require_permission(Permission.USAGE_READ)),
    db: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    service = UsageAnalyticsService(db)
    overview = await service.get_overview(hours=hours)
    return overview["top_endpoints"][:limit]


@router.get("/analytics/summary", response_model=AnalyticsSummaryRead)
async def admin_analytics_summary(
    hours: int = Query(default=24, ge=1, le=168),
    ctx: AdminContext = Depends(require_permission(Permission.USAGE_READ)),
    db: AsyncSession = Depends(get_session),
) -> AnalyticsSummaryRead:
    service = UsageAnalyticsService(db)
    overview = await service.get_overview(hours=hours)
    return AnalyticsSummaryRead(
        period=f"{hours}h",
        total_requests=overview["total_requests"],
        total_cost=overview["total_cost"],
        total_tokens=overview["total_tokens"],
        avg_latency_ms=0.0,
        avg_cost_per_request=overview["avg_cost_per_request"],
        error_rate=0.0,
        top_models=overview["top_models"],
        top_providers=overview["top_providers"],
        top_endpoints=overview["top_endpoints"],
    )