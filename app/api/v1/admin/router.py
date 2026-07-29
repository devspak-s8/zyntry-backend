from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.core.config import settings
from app.core.database import get_session
from app.models.users import User
from app.repositories import UnitOfWork
from app.schemas.admin import AdminProjectRead, AdminRuntimeRead, AdminSystemInfo, AdminUserRead
from app.models.organizations import Organization
from app.models.projects import Project
from app.models.runtimes import Runtime

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/stats", response_model=dict)
async def admin_stats(
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_session),
) -> dict:
    uow = UnitOfWork(db)
    now = datetime.now(timezone.utc)
    day_ago = now - __import__("datetime").timedelta(days=1)

    users_count = await db.scalar(select(func.count()).select_from(User))
    orgs_count = await db.scalar(select(func.count()).select_from(Organization))
    projects_count = await db.scalar(select(func.count()).select_from(Project))
    runtimes_count = await db.scalar(select(func.count()).select_from(Runtime))

    active_runtimes = await db.scalar(select(func.count()).select_from(Runtime).where(Runtime.status == "active"))
    queued_runtimes = await db.scalar(select(func.count()).select_from(Runtime).where(Runtime.status == "queued"))
    failed_runtimes = await db.scalar(select(func.count()).select_from(Runtime).where(Runtime.status == "failed"))

    from app.models.billing import Wallet, WalletTransaction, UsageLog
    total_wallet_balance = await db.scalar(select(func.coalesce(func.sum(Wallet.balance), 0)).where(Wallet.status == "active"))
    requests_24h = await db.scalar(select(func.count()).select_from(UsageLog).where(UsageLog.created_at >= day_ago))
    cost_24h = await db.scalar(select(func.coalesce(func.sum(UsageLog.cost), 0)).where(UsageLog.created_at >= day_ago))
    avg_latency_24h = await db.scalar(select(func.coalesce(func.avg(UsageLog.latency_ms), 0)).where(UsageLog.created_at >= day_ago))

    return {
        "total_users": users_count or 0,
        "total_organizations": orgs_count or 0,
        "total_projects": projects_count or 0,
        "total_runtimes": runtimes_count or 0,
        "total_wallet_balance": float(total_wallet_balance or 0),
        "total_requests_24h": requests_24h or 0,
        "total_cost_24h": float(cost_24h or 0),
        "avg_latency_ms_24h": float(avg_latency_24h or 0),
        "active_runtimes": active_runtimes or 0,
        "queued_runtimes": queued_runtimes or 0,
        "failed_runtimes": failed_runtimes or 0,
    }


@router.get("/users", response_model=list[AdminUserRead])
async def admin_list_users(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_session),
) -> list[AdminUserRead]:
    uow = UnitOfWork(db)
    users = await uow.users.list(limit=limit, offset=offset)
    return [
        AdminUserRead(
            id=str(u.id),
            email=u.email,
            name=u.name,
            organization_id=str(u.organization_id) if u.organization_id else None,
            is_active=u.is_active,
            created_at=u.created_at.isoformat() if u.created_at else "",
        )
        for u in users
    ]


@router.get("/projects", response_model=list[AdminProjectRead])
async def admin_list_projects(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_session),
) -> list[AdminProjectRead]:
    uow = UnitOfWork(db)
    projects = await uow.projects.list_all(limit=limit, offset=offset)
    return [
        AdminProjectRead(
            id=str(p.id),
            name=p.name,
            slug=p.slug,
            organization_id=str(p.organization_id),
            status=p.status or "ready",
            created_at=p.created_at.isoformat() if p.created_at else "",
        )
        for p in projects
    ]


@router.get("/runtimes", response_model=list[AdminRuntimeRead])
async def admin_list_runtimes(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_session),
) -> list[AdminRuntimeRead]:
    uow = UnitOfWork(db)
    runtimes = await uow.runtimes.list_all(limit=limit, offset=offset)
    return [
        AdminRuntimeRead(
            id=str(r.id),
            project_id=str(r.project_id),
            status=r.status,
            provider=r.provider,
            model=r.model,
            version=r.version,
            health=r.health,
            created_at=r.created_at.isoformat() if r.created_at else "",
        )
        for r in runtimes
    ]


@router.get("/system", response_model=AdminSystemInfo)
async def admin_system_info(
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_session),
) -> AdminSystemInfo:
    import sys
    from app.core.cache import cache as redis_cache

    redis_status = "connected"
    try:
        await redis_cache.client.ping()
    except Exception:
        redis_status = "disconnected"

    return AdminSystemInfo(
        app_name=settings.APP_NAME,
        app_env=settings.APP_ENV,
        app_version=settings.API_VERSION,
        database_url=settings.DATABASE_URL.split("@")[-1] if "@" in settings.DATABASE_URL else "configured",
        redis_url=f"redis://***:{settings.REDIS_PORT}",
        celery_broker_url="configured",
        vector_provider=settings.VECTOR_PROVIDER,
        rate_limit_per_minute=settings.RATE_LIMIT_PER_MINUTE,
        enable_memory=settings.ENABLE_MEMORY,
        enable_rag=settings.ENABLE_RAG,
        enable_analytics=settings.ENABLE_ANALYTICS,
        enable_tools=settings.ENABLE_TOOLS,
        enable_router=settings.ENABLE_ROUTER,
        uptime_seconds=time.time(),
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        redis_status=redis_status,
    )
