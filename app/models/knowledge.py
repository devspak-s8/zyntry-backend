from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.organizations import TimestampMixin, UUIDMixin


class KnowledgeBase(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "knowledge_bases"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    config: Mapped[dict] = mapped_column(JSONB, default=dict)


class Document(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "documents"

    title: Mapped[str] = mapped_column(String(512), nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(String(512), nullable=True)
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False
    )
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    doc_metadata: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class KnowledgeSource(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "knowledge_sources"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    sync_frequency: Mapped[str] = mapped_column(String(32), default="manual")
    last_synced_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    is_active: Mapped[bool] = mapped_column(default=True)
    connection_status: Mapped[str] = mapped_column(String(32), default="pending")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    sync_progress: Mapped[int] = mapped_column(Integer, default=0)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    credentials_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)


class SyncJob(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "sync_jobs"

    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_sources.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), default="queued")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    current_step: Mapped[str | None] = mapped_column(String(128), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    stats: Mapped[dict] = mapped_column(JSONB, default=dict)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    retry_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SyncSchedule(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "sync_schedules"

    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_sources.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    frequency: Mapped[str] = mapped_column(String(32), default="manual")
    status: Mapped[str] = mapped_column(String(32), default="active")
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    options: Mapped[dict] = mapped_column(JSONB, default=dict)
