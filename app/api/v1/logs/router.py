from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.core.database import get_session
from app.models.request_logs import RequestLog
from app.models.users import User
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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid project id") from None

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
            id=log.id,
            project_id=log.project_id,
            method=log.method,
            path=log.endpoint,
            status_code=log.status,
            latency_ms=log.latency_ms,
            tokens_used=log.tokens or 0,
            model=log.model,
            created_at=log.created_at.isoformat() if log.created_at else "",
        )
        for log in logs
    ]
