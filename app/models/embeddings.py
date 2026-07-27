from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.organizations import TimestampMixin, UUIDMixin


class Embedding(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "embeddings"

    vector: Mapped[list[float]] = mapped_column("vector", JSONB, nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
