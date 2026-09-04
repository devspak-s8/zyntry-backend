from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select

from app.models.events import Event
from app.models.notifications import Notification
from app.models.request_logs import RequestLog
from app.models.webhook_deliveries import WebhookDelivery
from app.models.webhook_subscriptions import WebhookSubscription
from app.repositories import UnitOfWork
from app.services.base import BaseService
from app.services.security.outbound import validate_outbound_url


class WebhookService(BaseService):
    def __init__(self, session) -> None:
        super().__init__(session)
        self.session = session
        self.uow = UnitOfWork(session)

    async def create_subscription(self, project_id: uuid.UUID, url: str, events: list[str], secret: str | None = None) -> WebhookSubscription:
        validate_outbound_url(url)
        sub = await self.uow.webhook_subscriptions.create(
            project_id=project_id,
            url=url,
            events=events,
            secret=secret,
        )
        await self.uow.commit()
        return sub

    async def list_subscriptions(self, project_id: uuid.UUID) -> list[WebhookSubscription]:
        result = await self.session.execute(
            select(WebhookSubscription).where(WebhookSubscription.project_id == project_id)
        )
        return list(result.scalars().all())

    async def get_subscription(self, subscription_id: uuid.UUID) -> WebhookSubscription | None:
        return await self.session.get(WebhookSubscription, subscription_id)

    async def delete_subscription(self, subscription_id: uuid.UUID) -> None:
        sub = await self.session.get(WebhookSubscription, subscription_id)
        if sub:
            await self.session.delete(sub)
            await self.session.flush()

    async def deliver_event(self, event_type: str, project_id: uuid.UUID | None, data: dict) -> None:
        from app.tasks.webhooks import deliver_webhook_task
        subs = await self.list_subscriptions(project_id)
        for sub in subs:
            if sub.active and (not sub.events or event_type in sub.events):
                deliver_webhook_task.delay(str(sub.id), event_type, data)

    async def list_deliveries(self, subscription_id: uuid.UUID, limit: int = 50, offset: int = 0) -> list[WebhookDelivery]:
        result = await self.session.execute(
            select(WebhookDelivery)
            .where(WebhookDelivery.subscription_id == subscription_id)
            .order_by(WebhookDelivery.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def replay_delivery(self, subscription_id: uuid.UUID, delivery_id: uuid.UUID) -> dict:
        delivery = await self.session.get(WebhookDelivery, delivery_id)
        if not delivery:
            raise ValueError("Delivery not found")
        sub = await self.session.get(WebhookSubscription, subscription_id)
        if not sub:
            raise ValueError("Subscription not found")
        from app.tasks.webhooks import deliver_webhook_task
        deliver_webhook_task.delay(str(sub.id), delivery.event_type, delivery.payload)
        return {"status": "queued"}


class EventService(BaseService):
    def __init__(self, session) -> None:
        super().__init__(session)
        self.session = session
        self.uow = UnitOfWork(session)

    async def emit(self, event_type: str, project_id: uuid.UUID | None, organization_id: uuid.UUID | None, data: dict | None = None) -> Event:
        event = await self.uow.events.create(
            project_id=project_id,
            organization_id=organization_id,
            event_type=event_type,
            data=data or {},
        )
        await self.uow.commit()
        # Event-triggered workflows use the same durable Celery queue as
        # schedules.  A workflow can opt in with
        # {"triggers": [{"event": "github.issue.created"}]}.
        if project_id is not None:
            workflows = await self.uow.workflows.get_by_project(project_id)
            for workflow in workflows:
                triggers = (workflow.definition or {}).get("triggers") or []
                if any(
                    isinstance(trigger, dict)
                    and trigger.get("enabled", True)
                    and trigger.get("event") in {event_type, "*"}
                    for trigger in triggers
                ):
                    try:
                        from app.tasks.workflows import run_workflow
                        run_workflow.delay(str(workflow.id), data or {})
                    except Exception:
                        # Queue outages must not roll back the event itself.
                        continue
        return event

    async def list_by_project(self, project_id: uuid.UUID, limit: int = 50, offset: int = 0) -> list[Event]:
        result = await self.session.execute(
            select(Event)
            .where(Event.project_id == project_id)
            .order_by(Event.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_by_org(self, organization_id: uuid.UUID, limit: int = 50, offset: int = 0) -> list[Event]:
        result = await self.session.execute(
            select(Event)
            .where(Event.organization_id == organization_id)
            .order_by(Event.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())


class RequestLogService(BaseService):
    def __init__(self, session) -> None:
        super().__init__(session)
        self.session = session
        self.uow = UnitOfWork(session)

    async def create(self, **kwargs) -> RequestLog:
        log = await self.uow.request_logs.create(**kwargs)
        await self.uow.commit()
        return log

    async def list_by_project(self, project_id: uuid.UUID, limit: int = 50, offset: int = 0) -> list[RequestLog]:
        result = await self.session.execute(
            select(RequestLog)
            .where(RequestLog.project_id == project_id)
            .order_by(RequestLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())


class NotificationService(BaseService):
    def __init__(self, session) -> None:
        super().__init__(session)
        self.session = session
        self.uow = UnitOfWork(session)

    async def create(self, user_id: uuid.UUID, type: str, title: str, message: str, data: dict | None = None) -> Notification:
        notification = await self.uow.notifications.create(
            user_id=user_id,
            type=type,
            title=title,
            message=message,
            data=data or {},
        )
        await self.uow.commit()
        return notification

    async def list_for_user(self, user_id: uuid.UUID, limit: int = 50, offset: int = 0) -> list[Notification]:
        result = await self.session.execute(
            select(Notification)
            .where(Notification.user_id == user_id)
            .order_by(Notification.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def mark_read(self, notification_id: uuid.UUID, user_id: uuid.UUID) -> Notification | None:
        notification = await self.session.get(Notification, notification_id)
        if notification and notification.user_id == user_id:
            notification.read = True
            await self.session.flush()
            await self.session.commit()
            return notification
        return None

    async def mark_all_read(self, user_id: uuid.UUID) -> None:
        result = await self.session.execute(
            select(Notification).where(Notification.user_id == user_id, Notification.read == False)
        )
        for notification in result.scalars().all():
            notification.read = True
        await self.session.flush()
        await self.session.commit()
