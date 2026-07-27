from __future__ import annotations

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
from app.schemas.admin import AdminStats, AdminProjectRead, AdminRuntimeRead, AdminSystemInfo, AdminUserRead
from app.models.organizations import Organization
from app.models.projects import Project
from app.models.runtimes import Runtime
from app.models.users import User as UserModel

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/stats", response_model=AdminStats)
async def admin_stats(
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_session),
) -> AdminStats:
    uow = UnitOfWork(db)
    try:
        users_count = len(await uow.users.list(limit=10000, offset=0))
        orgs_count = len(await uow.organizations.list(limit=10000, offset=0))
        projects_count = len(await uow.projects.list_all(limit=10000, offset=0))
        runtimes_count = len(await uow.runtimes.list_all(limit=10000, offset=0))
        sources_count = len(await uow.knowledge_sources.list_all(limit=10000, offset=0))
        api_keys_count = len(await uow.api_keys.list_all(limit=10000, offset=0))
        webhooks_count = len(await uow.webhook_subscriptions.list_all(limit=10000, offset=0))
    except Exception:
        users_count = 0
        orgs_count = 0
        projects_count = 0
        runtimes_count = 0
        sources_count = 0
        api_keys_count = 0
        webhooks_count = 0
    return AdminStats(
        total_users=users_count,
        total_organizations=orgs_count,
        total_projects=projects_count,
        total_runtimes=runtimes_count,
        total_knowledge_sources=sources_count,
        total_api_keys=api_keys_count,
        total_webhooks=webhooks_count,
        total_requests_24h=0,
        total_errors_24h=0,
        avg_latency_ms_24h=0.0,
        total_cost_cents_24h=0,
        active_runtimes=0,
        queued_runtimes=0,
        failed_runtimes=0,
    )


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
    import time
    import sys
    return AdminSystemInfo(
        app_name=settings.APP_NAME,
        app_env=settings.APP_ENV,
        app_version=settings.API_VERSION,
        database_url=settings.DATABASE_URL,
        redis_url=settings.redis_url,
        celery_broker_url=settings.CELERY_BROKER_URL,
        vector_provider=settings.VECTOR_PROVIDER,
        rate_limit_per_minute=settings.RATE_LIMIT_PER_MINUTE,
        enable_memory=settings.ENABLE_MEMORY,
        enable_rag=settings.ENABLE_RAG,
        enable_analytics=settings.ENABLE_ANALYTICS,
        enable_tools=settings.ENABLE_TOOLS,
        enable_router=settings.ENABLE_ROUTER,
        uptime_seconds=0.0,
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
    )