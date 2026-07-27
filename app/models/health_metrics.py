from __future__ import annotations

import uuid

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.organizations import TimestampMixin, UUIDMixin


class HealthMetric(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "health_metrics"

    runtime_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("runtimes.id", ondelete="CASCADE"), nullable=False
    )
    metric_type: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)


class RuntimeHealthCheck(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "runtime_health_checks"

    runtime_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("runtimes.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    health_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    embedding_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    retrieval_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    llm_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    token_usage: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    storage_usage: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    index_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    memory_usage_mb: Mapped[float | None] = mapped_column(Float, nullable=True)
    worker_queue_depth: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_sync_success: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_propagation_success: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cache_hit_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    retrieval_quality: Mapped[float | None] = mapped_column(Float, nullable=True)
    details: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)