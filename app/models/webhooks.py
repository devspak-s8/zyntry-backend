from __future__ import annotations

import uuid

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.organizations import TimestampMixin, UUIDMixin


class WebhookEvent(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "webhook_events"

    source: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    signature: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="received")
