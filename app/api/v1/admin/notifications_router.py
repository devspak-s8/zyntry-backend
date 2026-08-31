from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.constants import Permission
from app.admin.dependencies import AdminContext, require_permission
from app.admin.schemas import (
    NotificationConfigCreate,
    NotificationConfigRead,
    NotificationEventRead,
)
from app.admin.services.notifications import AdminNotificationService
from app.core.database import get_session
from app.admin.models import AdminEvent

router = APIRouter(prefix="/admin", tags=["admin-notifications"])


@router.get("/notifications/configs", response_model=list[NotificationConfigRead])
async def admin_list_notification_configs(
    event_type: str | None = Query(default=None),
    is_enabled: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    ctx: AdminContext = Depends(require_permission(Permission.NOTIFICATIONS_READ)),
    db: AsyncSession = Depends(get_session),
) -> list[NotificationConfigRead]:
    service = AdminNotificationService(db)
    configs = await service.list_configs(event_type=event_type, is_enabled=is_enabled, limit=limit, offset=offset)
    return [
        NotificationConfigRead(
            id=str(c.id) if c.id else None,
            event_type=c.event_type,
            provider_type=c.provider_type,
            name=c.name,
            is_enabled=c.is_enabled,
            config=c.config,
        )
        for c in configs
    ]


@router.post("/notifications/configs")
async def admin_create_notification_config(
    body: NotificationConfigCreate,
    ctx: AdminContext = Depends(require_permission(Permission.NOTIFICATIONS_WRITE)),
    db: AsyncSession = Depends(get_session),
) -> NotificationConfigRead:
    service = AdminNotificationService(db)
    config = await service.create_config(
        event_type=body.event_type,
        provider_type=body.provider_type,
        name=body.name,
        is_enabled=body.is_enabled,
        config=body.config,
    )
    await db.commit()
    return NotificationConfigRead(
        id=str(config.id) if config.id else None,
        event_type=config.event_type,
        provider_type=config.provider_type,
        name=config.name,
        is_enabled=config.is_enabled,
        config=config.config,
    )


@router.put("/notifications/configs/{config_id}/enable")
async def admin_enable_notification_config(
    config_id: str,
    ctx: AdminContext = Depends(require_permission(Permission.NOTIFICATIONS_WRITE)),
    db: AsyncSession = Depends(get_session),
) -> NotificationConfigRead:
    service = AdminNotificationService(db)
    config = await service.enable_config(config_id)
    if config is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification config not found")
    await db.commit()
    return NotificationConfigRead(
        id=str(config.id) if config.id else None,
        event_type=config.event_type,
        provider_type=config.provider_type,
        name=config.name,
        is_enabled=config.is_enabled,
        config=config.config,
    )


@router.put("/notifications/configs/{config_id}/disable")
async def admin_disable_notification_config(
    config_id: str,
    ctx: AdminContext = Depends(require_permission(Permission.NOTIFICATIONS_WRITE)),
    db: AsyncSession = Depends(get_session),
) -> NotificationConfigRead:
    service = AdminNotificationService(db)
    config = await service.disable_config(config_id)
    if config is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification config not found")
    await db.commit()
    return NotificationConfigRead(
        id=str(config.id) if config.id else None,
        event_type=config.event_type,
        provider_type=config.provider_type,
        name=config.name,
        is_enabled=config.is_enabled,
        config=config.config,
    )


@router.get("/notifications/events", response_model=list[NotificationEventRead])
async def admin_list_notification_events(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    ctx: AdminContext = Depends(require_permission(Permission.NOTIFICATIONS_READ)),
    db: AsyncSession = Depends(get_session),
) -> list[NotificationEventRead]:
    result = await db.execute(
        select(AdminEvent)
        .order_by(desc(AdminEvent.created_at))
        .offset(offset)
        .limit(limit)
    )
    return [
        NotificationEventRead(
            id=str(event.id),
            event_type=event.event_type,
            title=event.title,
            description=event.description,
            is_read=event.is_read,
            created_at=event.created_at.isoformat() if event.created_at else "",
        )
        for event in result.scalars().all()
    ]


@router.post("/notifications/events/{event_id}/read")
async def admin_mark_notification_read(
    event_id: str,
    ctx: AdminContext = Depends(require_permission(Permission.NOTIFICATIONS_READ)),
    db: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    event = await db.get(AdminEvent, event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    event.is_read = True
    await db.commit()
    return {"message": "Notification marked as read"}


@router.post("/notifications/events/read-all")
async def admin_mark_all_notifications_read(
    ctx: AdminContext = Depends(require_permission(Permission.NOTIFICATIONS_READ)),
    db: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    result = await db.execute(select(AdminEvent).where(AdminEvent.is_read.is_(False)))
    events = result.scalars().all()
    for event in events:
        event.is_read = True
    await db.commit()
    return {"message": f"Marked {len(events)} notifications as read"}
