from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.organizations import ORMModel


class WebhookSubscriptionCreate(ORMModel):
    url: str = Field(min_length=1, max_length=2048)
    events: list[str] = Field(default_factory=list)
    secret: str | None = Field(default=None, max_length=255)
    environment: Literal["development", "staging", "production"] = "development"


class WebhookSubscriptionRead(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    environment: str = "development"
    url: str
    events: list[str]
    secret: str | None
    active: bool
    last_delivery_at: str | None


class WebhookDeliveryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    subscription_id: uuid.UUID
    event_type: str
    response_status: int | None
    response_body: str | None
    latency_ms: int | None
    attempts: int
    delivered_at: str | None
    created_at: str
