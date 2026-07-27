from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.organizations import TimestampMixin, UUIDMixin


class WebhookSubscription(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "webhook_subscriptions"

    project_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    events: Mapped[list[str]] = mapped_column(JSONB, default=list)
    secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=3)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=10)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_delivery_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
