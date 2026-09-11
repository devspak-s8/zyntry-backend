from __future__ import annotations

import asyncio
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.constants import Permission
from app.admin.dependencies import AdminContext, require_permission
from app.admin.schemas import (
    EventReplayRead,
    EventTimelineRead,
)
from app.admin.services.event_timeline import EventTimelineService
from app.core.database import async_session_factory, get_session

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
            id=str(e.id),
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
            cost=e.cost,
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
            id=str(e.id),
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
            cost=e.cost,
            data=e.data,
        )
        for e in events
    ]


@router.get("/events/requests/stream")
async def admin_stream_events(
    limit: int = Query(default=20, ge=1, le=100),
    interval_seconds: float = Query(default=2.0, ge=0.5, le=30.0),
    ctx: AdminContext = Depends(require_permission(Permission.EVENTS_READ)),
) -> StreamingResponse:
    """Stream new invocation events as server-sent events for the admin console."""

    async def event_generator():
        seen: set[str] = set()
        try:
            while True:
                async with async_session_factory() as stream_db:
                    events = await EventTimelineService(stream_db).list_events(limit=limit, offset=0)
                    for event in reversed(events):
                        event_id = str(event.id)
                        if event_id in seen:
                            continue
                        seen.add(event_id)
                        payload = {
                            "id": event_id,
                            "request_id": event.request_id,
                            "event_type": event.event_type,
                            "title": event.title,
                            "description": event.description,
                            "sequence": event.sequence,
                            "timestamp": event.created_at.isoformat() if event.created_at else "",
                            "organization_id": str(event.organization_id) if event.organization_id else None,
                            "user_id": str(event.user_id) if event.user_id else None,
                            "runtime_id": str(event.runtime_id) if event.runtime_id else None,
                            "provider": event.provider,
                            "model": event.model,
                            "latency_ms": event.latency_ms,
                            "status_code": event.status_code,
                            "cost": float(event.cost) if event.cost else None,
                            "data": event.data,
                        }
                        yield f"event: invocation\ndata: {json.dumps(payload, default=str)}\n\n"
                if len(seen) > 500:
                    seen = set(list(seen)[-100:])
                yield ": heartbeat\n\n"
                await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            return

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )
