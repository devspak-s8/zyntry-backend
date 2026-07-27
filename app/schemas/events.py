from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict

from app.schemas.organizations import ORMModel


class EventRead(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID | None
    organization_id: uuid.UUID | None
    event_type: str
    data: dict
    created_at: str


class RequestLogRead(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID | None
    method: str
    path: str
    status_code: int
    latency_ms: float
    tokens_used: int
    model: str | None
    created_at: str


class NotificationRead(ORMModel):
    id: uuid.UUID
    user_id: uuid.UUID | None
    title: str
    message: str
    is_read: bool
    created_at: str


class NotificationUpdate(BaseModel):
    is_read: bool | None = None
