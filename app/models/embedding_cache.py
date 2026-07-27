from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.organizations import TimestampMixin, UUIDMixin


class EmbeddingCache(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "embedding_caches"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    embedding_version: Mapped[str] = mapped_column(String(32), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(128), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    vector: Mapped[list[float]] = mapped_column(JSONB, nullable=False)
    meta: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index(
            "ix_embedding_caches_project_content_version",
            "project_id",
            "content_hash",
            "embedding_version",
        ),
        Index(
            "ix_embedding_caches_lookup",
            "project_id",
            "content_hash",
            "embedding_version",
            "embedding_model",
            "provider",
            unique=True,
        ),
    )
