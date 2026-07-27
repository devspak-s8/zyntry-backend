from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.api.v1.dependencies import get_current_user
from app.core.database import get_session
from app.models.users import User
from app.models.events import Event
from app.models.request_logs import RequestLog
from app.repositories import UnitOfWork
from app.schemas.events import EventRead, RequestLogRead

router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=list[EventRead])
async def list_events(
    project_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> list[EventRead]:
    stmt = select(Event).order_by(Event.created_at.desc()).limit(limit).offset(offset)
    if project_id:
        try:
            pid = uuid.UUID(project_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid project id")
        stmt = stmt.where(Event.project_id == pid)

    result = await db.execute(stmt)
    events = result.scalars().all()
    return [
        EventRead(
            id=e.id,
            project_id=e.project_id,
            organization_id=e.organization_id,
            event_type=e.event_type,
            data=e.data,
            created_at=e.created_at.isoformat() if e.created_at else "",
        )
        for e in events
    ]
