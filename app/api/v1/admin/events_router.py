from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.constants import Permission
from app.admin.dependencies import AdminContext, require_permission
from app.admin.schemas import (
    EventReplayRead,
    EventTimelineRead,
)
from app.admin.services.event_timeline import EventTimelineService
from app.core.database import get_session

router = APIRouter(prefix="/admin", tags=["admin-events"])


@router.get("/events", response_model=list[EventTimelineRead])
async def admin_list_events(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    organization_id: str | None = Query(default=None),
    user_id: str | None = Query(default=None),
    runtime_id: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    ctx: AdminContext = Depends(require_permission(Permission.EVENTS_READ)),
    db: AsyncSession = Depends(get_session),
) -> list[EventTimelineRead]:
    service = EventTimelineService(db)
    date_from_dt = datetime.fromisoformat(date_from) if date_from else None
    date_to_dt = datetime.fromisoformat(date_to) if date_to else None
    events = await service.list_events(
        limit=limit,
        offset=offset,
        organization_id=organization_id,
        user_id=user_id,
        runtime_id=runtime_id,
        date_from=date_from_dt,
        date_to=date_to_dt,
        event_type=event_type,
    )
    return [
        EventTimelineRead(
            id=str(e.id) if e.id else None,
            request_id=e.request_id,
            event_type=e.event_type,
            title=e.title,
            description=e.description,
            sequence=e.sequence,
            timestamp=e.created_at.isoformat() if e.created_at else "",
            organization_id=str(e.organization_id) if e.organization_id else None,
            user_id=str(e.user_id) if e.user_id else None,
            runtime_id=str(e.runtime_id) if e.runtime_id else None,
            provider=e.provider,
            model=e.model,
            latency_ms=e.latency_ms,
            status_code=e.status_code,
            cost=float(e.cost) if e.cost else None,
            data=e.data,
        )
        for e in events
    ]


@router.get("/events/request/{request_id}", response_model=EventReplayRead)
async def admin_get_event_timeline(
    request_id: str,
    ctx: AdminContext = Depends(require_permission(Permission.EVENTS_READ)),
    db: AsyncSession = Depends(get_session),
) -> EventReplayRead | None:
    service = EventTimelineService(db)
    replay = await service.get_request_replay(request_id)
    if replay is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
    return EventReplayRead(**replay)


@router.get("/events/request/{request_id}/replay", response_model=EventReplayRead)
async def admin_replay_request(
    request_id: str,
    ctx: AdminContext = Depends(require_permission(Permission.EVENTS_REPLAY)),
    db: AsyncSession = Depends(get_session),
) -> EventReplayRead:
    service = EventTimelineService(db)
    replay = await service.get_request_replay(request_id)
    if replay is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
    return EventReplayRead(**replay)


@router.get("/events/requests/live", response_model=list[EventTimelineRead])
async def admin_live_events(
    limit: int = Query(default=20, ge=1, le=100),
    ctx: AdminContext = Depends(require_permission(Permission.EVENTS_READ)),
    db: AsyncSession = Depends(get_session),
) -> list[EventTimelineRead]:
    service = EventTimelineService(db)
    events = await service.list_events(limit=limit, offset=0)
    return [
        EventTimelineRead(
            id=str(e.id) if e.id else None,
            request_id=e.request_id,
            event_type=e.event_type,
            title=e.title,
            description=e.description,
            sequence=e.sequence,
            timestamp=e.created_at.isoformat() if e.created_at else "",
            organization_id=str(e.organization_id) if e.organization_id else None,
            user_id=str(e.user_id) if e.user_id else None,
            runtime_id=str(e.runtime_id) if e.runtime_id else None,
            provider=e.provider,
            model=e.model,
            latency_ms=e.latency_ms,
            status_code=e.status_code,
            cost=float(e.cost) if e.cost else None,
            data=e.data,
        )
        for e in events
    ]