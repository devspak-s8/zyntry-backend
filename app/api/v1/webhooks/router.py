from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.core.database import get_session
from app.models.users import User
from app.models.webhook_deliveries import WebhookDelivery
from app.models.webhook_subscriptions import WebhookSubscription
from app.repositories import UnitOfWork
from app.schemas.webhooks import WebhookDeliveryRead, WebhookSubscriptionCreate, WebhookSubscriptionRead
from app.services.webhooks import WebhookService
from app.api.v1.dependencies_tenant import require_project_membership
from app.services.security.outbound import validate_outbound_url
import uuid

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _safe_secret(value: str | None) -> None:
    # Webhook signing material is write-only. The caller receives it only
    # during creation through a separate secure channel, never from reads.
    return None


@router.get("", response_model=list[WebhookSubscriptionRead])
async def list_webhooks(
    project_id: Annotated[str, Query()],
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> list[WebhookSubscriptionRead]:
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project id")
    await require_project_membership(project_id, current_user, db)
    service = WebhookService(db)
    subs = await service.list_subscriptions(pid)
    return [
        WebhookSubscriptionRead(
            id=s.id,
            project_id=s.project_id,
            url=s.url,
            events=s.events,
            secret=_safe_secret(s.secret),
            active=s.active,
            last_delivery_at=s.last_delivery_at,
        )
        for s in subs
    ]


@router.post("", response_model=WebhookSubscriptionRead, status_code=status.HTTP_201_CREATED)
async def create_webhook(
    body: WebhookSubscriptionCreate,
    project_id: Annotated[str, Query()],
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> WebhookSubscriptionRead:
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project id")
    await require_project_membership(project_id, current_user, db)
    try:
        validate_outbound_url(body.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    service = WebhookService(db)
    sub = await service.create_subscription(pid, body.url, body.events, body.secret)
    return WebhookSubscriptionRead(
        id=sub.id,
        project_id=sub.project_id,
        url=sub.url,
        events=sub.events,
        secret=_safe_secret(sub.secret),
        active=sub.active,
        last_delivery_at=sub.last_delivery_at,
    )


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(
    webhook_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> None:
    try:
        wid = uuid.UUID(webhook_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid webhook id")
    service = WebhookService(db)
    sub = await service.get_subscription(wid)
    if sub is None:
        raise HTTPException(status_code=404, detail="Webhook not found")
    await require_project_membership(str(sub.project_id), current_user, db)
    await service.delete_subscription(wid)


@router.get("/events", response_model=list[str])
async def list_webhook_event_types(
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[str]:
    return [
        "user.created",
        "user.verified",
        "user.login",
        "user.logout",
        "project.created",
        "project.updated",
        "project.deleted",
        "project.provisioning.started",
        "project.provisioning.completed",
        "project.provisioning.failed",
        "knowledge.upload.started",
        "knowledge.upload.completed",
        "knowledge.upload.failed",
        "knowledge.sync.started",
        "knowledge.sync.completed",
        "knowledge.sync.failed",
        "knowledge.deleted",
        "chat.started",
        "chat.completed",
        "chat.failed",
        "search.completed",
        "search.failed",
        "summarize.completed",
        "extract.completed",
        "classify.completed",
        "api_key.created",
        "api_key.rotated",
        "api_key.revoked",
        "api_key.expired",
        "payment.succeeded",
        "payment.failed",
        "invoice.created",
        "usage.limit.reached",
        "credits.low",
    ]


@router.get("/{webhook_id}/deliveries", response_model=list[WebhookDeliveryRead])
async def list_webhook_deliveries(
    webhook_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> list[WebhookDeliveryRead]:
    try:
        wid = uuid.UUID(webhook_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid webhook id")
    service = WebhookService(db)
    sub = await service.get_subscription(wid)
    if sub is None:
        raise HTTPException(status_code=404, detail="Webhook not found")
    await require_project_membership(str(sub.project_id), current_user, db)
    deliveries = await service.list_deliveries(wid)
    return [
        WebhookDeliveryRead(
            id=d.id,
            subscription_id=d.subscription_id,
            event_type=d.event_type,
            response_status=d.response_status,
            response_body=d.response_body,
            latency_ms=d.latency_ms,
            attempts=d.attempts,
            delivered_at=d.delivered_at.isoformat() if d.delivered_at else None,
            created_at=d.created_at.isoformat() if d.created_at else "",
        )
        for d in deliveries
    ]


@router.post("/{webhook_id}/deliveries/{delivery_id}/replay", tags=["webhooks"])
async def replay_webhook_delivery(
    webhook_id: str,
    delivery_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> dict:
    try:
        wid = uuid.UUID(webhook_id)
        did = uuid.UUID(delivery_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid id")
    service = WebhookService(db)
    sub = await service.get_subscription(wid)
    if sub is None:
        raise HTTPException(status_code=404, detail="Webhook not found")
    await require_project_membership(str(sub.project_id), current_user, db)
    result = await service.replay_delivery(wid, did)
    return result
