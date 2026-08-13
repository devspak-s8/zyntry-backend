from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Float, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.organizations import TimestampMixin, UUIDMixin


class RuntimeAssistantConversation(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "runtime_assistant_conversations"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    runtime_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("runtimes.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    environment: Mapped[str] = mapped_column(String(32), default="production")
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="active")

    __table_args__ = (
        Index(
            "ix_runtime_assistant_conversation_scope",
            "organization_id",
            "project_id",
            "runtime_id",
            "user_id",
        ),
    )


class RuntimeAssistantMessage(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "runtime_assistant_messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("runtime_assistant_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(String(24), default="observe")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)

    __table_args__ = (
        Index("ix_runtime_assistant_messages_conversation_created", "conversation_id", "created_at"),
    )


class RuntimeAssistantEvidence(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "runtime_assistant_evidence"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("runtime_assistant_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("runtime_assistant_messages.id", ondelete="CASCADE"), nullable=False
    )
    evidence_type: Mapped[str] = mapped_column(String(48), nullable=False)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    reference_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
    deep_link: Mapped[str | None] = mapped_column(String(512), nullable=True)
    redacted: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (
        Index("ix_runtime_assistant_evidence_message", "message_id"),
        Index("ix_runtime_assistant_evidence_reference", "reference_id"),
    )
