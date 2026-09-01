from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.constants import Permission
from app.admin.dependencies import AdminContext, require_permission
from app.admin.schemas import (
    RuntimeDetailRead,
    RuntimeUsageRead,
)
from app.admin.services.runtime_monitor import RuntimeMonitorService
from app.core.database import get_session

router = APIRouter(prefix="/admin", tags=["admin-runtimes"])


@router.get("/runtimes", response_model=list[RuntimeDetailRead])
async def admin_list_runtimes(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    ctx: AdminContext = Depends(require_permission(Permission.RUNTIMES_READ)),
    db: AsyncSession = Depends(get_session),
) -> list[RuntimeDetailRead]:
    service = RuntimeMonitorService(db)
    runtimes = await service.get_all_runtimes(limit=limit, offset=offset)
    return [RuntimeDetailRead(**r) for r in runtimes]


@router.get("/runtimes/{runtime_id}", response_model=RuntimeDetailRead)
async def admin_get_runtime(
    runtime_id: str,
    ctx: AdminContext = Depends(require_permission(Permission.RUNTIMES_READ)),
    db: AsyncSession = Depends(get_session),
) -> RuntimeDetailRead:
    service = RuntimeMonitorService(db)
    runtime = await service.get_runtime_detail(runtime_id)
    if runtime is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Runtime not found")
    return RuntimeDetailRead(**runtime)


@router.post("/runtimes/{runtime_id}/disable")
async def admin_disable_runtime(
    runtime_id: str,
    ctx: AdminContext = Depends(require_permission(Permission.RUNTIMES_WRITE)),
    db: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    service = RuntimeMonitorService(db)
    if not await service.disable_runtime(runtime_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Runtime not found")
    await db.commit()
    return {"message": "Runtime disabled"}


@router.post("/runtimes/{runtime_id}/restart")
async def admin_restart_runtime(
    runtime_id: str,
    ctx: AdminContext = Depends(require_permission(Permission.RUNTIMES_WRITE)),
    db: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    service = RuntimeMonitorService(db)
    if not await service.restart_runtime(runtime_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Runtime not found")
    await db.commit()
    return {"message": "Runtime restart queued"}


@router.post("/runtimes/{runtime_id}/flush-cache")
async def admin_flush_cache(
    runtime_id: str,
    ctx: AdminContext = Depends(require_permission(Permission.RUNTIMES_WRITE)),
    db: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    service = RuntimeMonitorService(db)
    if await service.get_runtime_detail(runtime_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Runtime not found")
    await service.flush_cache(runtime_id)
    return {"message": "Cache flushed"}


@router.post("/runtimes/{runtime_id}/regenerate")
async def admin_regenerate_runtime(
    runtime_id: str,
    ctx: AdminContext = Depends(require_permission(Permission.RUNTIMES_WRITE)),
    db: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    service = RuntimeMonitorService(db)
    if await service.get_runtime_detail(runtime_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Runtime not found")
    await service.regenerate_runtime(runtime_id)
    return {"message": "Runtime regeneration queued"}


@router.get("/runtimes/{runtime_id}/usage", response_model=RuntimeUsageRead)
async def admin_runtime_usage(
    runtime_id: str,
    ctx: AdminContext = Depends(require_permission(Permission.RUNTIMES_READ)),
    db: AsyncSession = Depends(get_session),
) -> RuntimeUsageRead:
    service = RuntimeMonitorService(db)
    usage = await service.get_runtime_usage(runtime_id)
    if usage is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Runtime not found")
    return RuntimeUsageRead(**usage)
