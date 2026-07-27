from __future__ import annotations

from app.models.events import Event
from app.models.notifications import Notification
from app.models.request_logs import RequestLog
from app.models.webhook_subscriptions import WebhookSubscription
from app.repositories.base import BaseRepository


class WebhookSubscriptionRepository(BaseRepository[WebhookSubscription]):
    model = WebhookSubscription


class EventRepository(BaseRepository[Event]):
    model = Event


class RequestLogRepository(BaseRepository[RequestLog]):
    model = RequestLog


class NotificationRepository(BaseRepository[Notification]):
    model = Notification
