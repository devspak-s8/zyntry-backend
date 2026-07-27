from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.core.database import get_session
from app.models.users import User
from app.repositories import UnitOfWork
from app.schemas.events import NotificationRead, NotificationUpdate

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationRead])
async def list_notifications(
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> list[NotificationRead]:
    uow = UnitOfWork(db)
    notifications = await uow.notifications.list(limit=limit, offset=offset)
    # Filter by user in memory for now since repo is basic
    user_notifications = [n for n in notifications if str(n.user_id) == str(current_user.id)]
    return [
        NotificationRead(
            id=n.id,
            user_id=n.user_id,
            type=n.type,
            title=n.title,
            message=n.message,
            data=n.data,
            read=n.read,
            created_at=n.created_at.isoformat() if n.created_at else "",
        )
        for n in user_notifications
    ]


@router.patch("/{notification_id}", response_model=NotificationRead)
async def update_notification(
    notification_id: str,
    body: NotificationUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> NotificationRead:
    from app.models.notifications import Notification
    from app.services.webhooks import NotificationService

    try:
        nid = uuid.UUID(notification_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid notification id")

    service = NotificationService(db)
    notification = await service.mark_read(nid, current_user.id)
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")

    return NotificationRead(
        id=notification.id,
        user_id=notification.user_id,
        type=notification.type,
        title=notification.title,
        message=notification.message,
        data=notification.data,
        read=notification.read,
        created_at=notification.created_at.isoformat() if notification.created_at else "",
    )
