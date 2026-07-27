from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict

from app.schemas.organizations import ORMModel


class NotificationRead(ORMModel):
    id: uuid.UUID
    user_id: uuid.UUID
    type: str
    title: str
    message: str
    data: dict
    read: bool
    created_at: str


class NotificationUpdate(ORMModel):
    read: bool | None = None


class WebhookSubscriptionCreate(BaseModel):
    url: str
    secret: str | None = None
    events: list[str] | None = None


class WebhookSubscriptionRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    url: str
    secret: str | None
    events: list[str]
    is_active: bool
    created_at: str
