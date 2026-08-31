from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.constants import HealthStatus, Permission
from app.admin.dependencies import AdminContext, require_permission
from app.admin.schemas import (
    HealthCheckRead,
    ProviderHealthRead,
    SystemHealthRead,
)
from app.admin.services.system_health import SystemHealthService
from app.core.database import get_session

router = APIRouter(prefix="/admin", tags=["admin-health"])


@router.get("/health/system", response_model=SystemHealthRead)
async def admin_system_health(
    ctx: AdminContext = Depends(require_permission(Permission.HEALTH_READ)),
    db: AsyncSession = Depends(get_session),
) -> SystemHealthRead:
    service = SystemHealthService(db)
    health = await service.get_full_health()
    checks = {}
    for name, check in health.get("checks", {}).items():
        checks[name] = HealthCheckRead(
            service=check.get("service", name),
            status=check.get("status", HealthStatus.HEALTHY.value),
            duration_ms=check.get("duration_ms", 0.0),
            details=check.get("details"),
        )
    providers = [ProviderHealthRead(**provider) for provider in await service.check_model_providers()]
    return SystemHealthRead(
        overall=health.get("overall", HealthStatus.HEALTHY.value),
        checks=checks,
        providers=providers,
    )


@router.get("/health/services", response_model=list[HealthCheckRead])
async def admin_health_services(
    ctx: AdminContext = Depends(require_permission(Permission.HEALTH_READ)),
    db: AsyncSession = Depends(get_session),
) -> list[HealthCheckRead]:
    service = SystemHealthService(db)
    health = await service.get_full_health()
    checks = []
    for name, check in health.get("checks", {}).items():
        checks.append(HealthCheckRead(
            service=check.get("service", name),
            status=check.get("status", HealthStatus.HEALTHY.value),
            duration_ms=check.get("duration_ms", 0.0),
            details=check.get("details"),
        ))
    return checks


@router.get("/health/services/{service_name}", response_model=HealthCheckRead)
async def admin_health_service(
    service_name: str,
    ctx: AdminContext = Depends(require_permission(Permission.HEALTH_READ)),
    db: AsyncSession = Depends(get_session),
) -> HealthCheckRead:
    service = SystemHealthService(db)
    health = await service.get_full_health()
    check = health.get("checks", {}).get(service_name)
    if check is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service not found")
    return HealthCheckRead(
        service=check.get("service", service_name),
        status=check.get("status", HealthStatus.HEALTHY.value),
        duration_ms=check.get("duration_ms", 0.0),
        details=check.get("details"),
    )


@router.get("/health/providers", response_model=list[ProviderHealthRead])
async def admin_provider_health(
    ctx: AdminContext = Depends(require_permission(Permission.HEALTH_READ)),
    db: AsyncSession = Depends(get_session),
) -> list[ProviderHealthRead]:
    service = SystemHealthService(db)
    providers = await service.check_model_providers()
    return [ProviderHealthRead(**p) for p in providers]
