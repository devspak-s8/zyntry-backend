from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.api.v1.dependencies import get_current_user
from app.core.database import get_session
from app.models.users import User
from app.models.request_logs import RequestLog
from app.schemas.events import RequestLogRead

router = APIRouter(prefix="/logs", tags=["logs"])


@router.get("", response_model=list[RequestLogRead])
async def list_logs(
    project_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> list[RequestLogRead]:
    stmt = select(RequestLog).order_by(RequestLog.created_at.desc()).limit(limit).offset(offset)
    if project_id:
        try:
            pid = uuid.UUID(project_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid project id")
        stmt = stmt.where(RequestLog.project_id == pid)

    result = await db.execute(stmt)
    logs = result.scalars().all()
    return [
        RequestLogRead(
            id=l.id,
            project_id=l.project_id,
            request_id=l.request_id,
            method=l.method,
            endpoint=l.endpoint,
            status=l.status,
            latency_ms=l.latency_ms,
            tokens=l.tokens,
            provider=l.provider,
            model=l.model,
            cost=l.cost,
            started_at=l.started_at,
            completed_at=l.completed_at,
            user_id=l.user_id,
            ip=l.ip,
            created_at=l.created_at.isoformat() if l.created_at else "",
        )
        for l in logs
    ]
