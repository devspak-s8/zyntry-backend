from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.organizations import TimestampMixin, UUIDMixin


class Conversation(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "conversations"

    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class Message(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "messages"

    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(String, nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
