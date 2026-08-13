from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.api.v1.dependencies import get_current_user
from app.core.database import get_session
from app.models.users import User
from app.models.request_logs import RequestLog
from app.schemas.events import RequestLogRead

router = APIRouter(prefix="/logs", tags=["logs"])


@router.get("", response_model=list[RequestLogRead])
async def list_logs(
    project_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> list[RequestLogRead]:
    if project_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="project_id is required")

    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid project id")

    from app.models.projects import Project
    project = await db.get(Project, pid)
    if project is None or project.organization_id != current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    stmt = (
        select(RequestLog)
        .where(RequestLog.project_id == pid)
        .order_by(RequestLog.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    logs = result.scalars().all()
    return [
        RequestLogRead(
            id=l.id,
            project_id=l.project_id,
            method=l.method,
            path=l.endpoint,
            status_code=l.status,
            latency_ms=l.latency_ms,
            tokens_used=l.tokens or 0,
            model=l.model,
            created_at=l.created_at.isoformat() if l.created_at else "",
        )
        for l in logs
    ]
