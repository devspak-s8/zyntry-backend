from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.constants import Permission
from app.admin.dependencies import AdminContext, require_permission
from app.admin.schemas import (
    RequestLogRead,
    RequestLogStatsRead,
)
from app.core.database import get_session

router = APIRouter(prefix="/admin", tags=["admin-requests"])


@router.get("/requests", response_model=list[RequestLogRead])
async def admin_list_requests(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    organization_id: str | None = Query(default=None),
    runtime_id: str | None = Query(default=None),
    user_id: str | None = Query(default=None),
    provider: str | None = Query(default=None),
    status_code: int | None = Query(default=None),
    ip_address: str | None = Query(default=None),
    country: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    endpoint: str | None = Query(default=None),
    ctx: AdminContext = Depends(require_permission(Permission.REQUESTS_READ)),
    db: AsyncSession = Depends(get_session),
) -> list[RequestLogRead]:
    return []


@router.get("/requests/stats", response_model=RequestLogStatsRead)
async def admin_request_stats(
    ctx: AdminContext = Depends(require_permission(Permission.REQUESTS_READ)),
    db: AsyncSession = Depends(get_session),
) -> RequestLogStatsRead:
    return RequestLogStatsRead(
        total_requests=0,
        avg_latency_ms=0.0,
        avg_cost=0.0,
        error_rate=0.0,
        p95_latency_ms=0.0,
        p99_latency_ms=0.0,
    )