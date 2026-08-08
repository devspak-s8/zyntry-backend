from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.constants import Permission
from app.admin.dependencies import (
    AdminContext,
    require_permission,
    require_super_admin,
)
from app.admin.schemas import (
    ModelAnalyticsRead,
    ProviderPerformanceRead,
)
from app.admin.services.model_analytics import ModelAnalyticsService
from app.core.database import get_session

router = APIRouter(prefix="/admin", tags=["admin-models"])


@router.get("/models", response_model=list[dict[str, Any]])
async def admin_list_models(
    ctx: AdminContext = Depends(require_permission(Permission.MODELS_READ)),
    db: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    service = ModelAnalyticsService(db)
    analytics = await service.get_provider_model_analytics()
    return [
        {
            "id": a.get("provider", ""),
            "name": a.get("provider", ""),
            "status": "healthy",
            "latency_ms": a.get("avg_latency_ms", 0),
            "model": a.get("model", ""),
            "requests": a.get("requests", 0),
        }
        for a in analytics
    ]


@router.get("/models/analytics", response_model=list[ModelAnalyticsRead])
async def admin_model_analytics(
    since: str | None = Query(default=None),
    ctx: AdminContext = Depends(require_permission(Permission.MODELS_READ)),
    db: AsyncSession = Depends(get_session),
) -> list[ModelAnalyticsRead]:
    service = ModelAnalyticsService(db)
    since_dt = datetime.fromisoformat(since) if since else None
    analytics = await service.get_provider_model_analytics(since=since_dt)
    return [ModelAnalyticsRead(**a) for a in analytics]


@router.get("/models/performance", response_model=list[ProviderPerformanceRead])
async def admin_provider_performance(
    since: str | None = Query(default=None),
    ctx: AdminContext = Depends(require_permission(Permission.MODELS_READ)),
    db: AsyncSession = Depends(get_session),
) -> list[ProviderPerformanceRead]:
    service = ModelAnalyticsService(db)
    since_dt = datetime.fromisoformat(since) if since else None
    performance = await service.get_provider_performance(since=since_dt)
    return [ProviderPerformanceRead(**p) for p in performance]


@router.get("/models/recommendations", response_model=list[dict[str, Any]])
async def admin_model_recommendations(
    ctx: AdminContext = Depends(require_permission(Permission.MODELS_READ)),
    db: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    service = ModelAnalyticsService(db)
    analytics = await service.get_provider_model_analytics()
    recommendations = await service.get_provider_recommendations(analytics)
    return recommendations


@router.post("/models/refresh")
async def admin_refresh_models(
    ctx: AdminContext = Depends(require_super_admin),
    db: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    return {"message": "Model analytics refreshed"}
