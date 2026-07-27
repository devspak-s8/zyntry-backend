from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.organizations import TimestampMixin, UUIDMixin


class Runtime(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "runtimes"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    version: Mapped[str] = mapped_column(String(32), default="1.0.0", nullable=False)
    provider: Mapped[str] = mapped_column(String(64), default="openai", nullable=False)
    model: Mapped[str] = mapped_column(String(128), default="gpt-4o", nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(128), default="text-embedding-3-small", nullable=False)
    vector_store: Mapped[str] = mapped_column(String(64), default="pgvector", nullable=False)
    chunk_size: Mapped[int] = mapped_column(Integer, default=512, nullable=False)
    chunk_overlap: Mapped[int] = mapped_column(Integer, default=64, nullable=False)
    documents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    chunks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    embeddings: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    index_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_build_started: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_build_completed: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_propagated: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    health: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    api_key_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True
    )
    config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)


class RuntimeBuildLog(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "runtime_build_logs"

    runtime_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("runtimes.id", ondelete="CASCADE"), nullable=False
    )
    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="started", nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)


class RuntimeBuildChunk(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "runtime_build_chunks"

    runtime_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("runtimes.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    action: Mapped[str] = mapped_column(String(16), default="new", nullable=False)
    embedded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    indexed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    embedding_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)
