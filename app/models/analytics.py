from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.organizations import TimestampMixin, UUIDMixin


class UsageEvent(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "usage_events"

    metric: Mapped[str] = mapped_column(String(64), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
