from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.organizations import TimestampMixin, UUIDMixin


class MemoryRecord(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "memory_records"

    key: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[dict] = mapped_column(JSONB, default=dict)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    memory_type: Mapped[str] = mapped_column(String(32), default="long_term", nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=True
    )
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    parent_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
