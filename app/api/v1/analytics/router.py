from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.api.v1.dependencies_tenant import require_project_membership
from app.core.database import get_session
from app.models.users import User
from app.repositories import UnitOfWork
from app.schemas.analytics import UsageEventCreate, UsageEventRead, UsageSummary
from app.services.analytics import AnalyticsService

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("", response_model=list[UsageEventRead])
async def list_usage_events(
    current_user: Annotated[User, Depends(get_current_user)],
    project_id: str,
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_session),
) -> list[UsageEventRead]:
    await require_project_membership(project_id, current_user, db)
    uow = UnitOfWork(db)
    service = AnalyticsService(uow)
    events = await service.list_events(project_id, limit=limit, offset=offset)
    return [
        UsageEventRead(
            id=e["id"],
            metric=e["metric"],
            quantity=e.get("quantity", 0),
            model=e.get("model"),
            provider=e.get("provider"),
            project_id=e.get("project_id"),
            metadata=e.get("metadata", {}),
            created_at=e.get("created_at") or datetime.now(timezone.utc),
        )
        for e in events
    ]


@router.post("", response_model=UsageEventRead, status_code=status.HTTP_201_CREATED)
async def create_usage_event(
    body: UsageEventCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> UsageEventRead:
    await require_project_membership(str(body.project_id), current_user, db)
    uow = UnitOfWork(db)
    service = AnalyticsService(uow)
    event = await service.create_event(body)
    return UsageEventRead(
        id=event["id"],
        metric=event["metric"],
        quantity=event.get("quantity", 0),
        model=event.get("model"),
        provider=event.get("provider"),
        project_id=event.get("project_id"),
        metadata=event.get("metadata", {}),
        created_at="",
    )


@router.get("/summary", response_model=UsageSummary)
async def get_usage_summary(
    current_user: Annotated[User, Depends(get_current_user)],
    project_id: str,
    db: AsyncSession = Depends(get_session),
) -> UsageSummary:
    await require_project_membership(project_id, current_user, db)
    uow = UnitOfWork(db)
    service = AnalyticsService(uow)
    summary = await service.get_summary(project_id)
    return UsageSummary(**summary)
