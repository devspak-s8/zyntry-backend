from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.organizations import TimestampMixin, UUIDMixin


class OnboardingTraceEvent(Base, UUIDMixin, TimestampMixin):
    """Privacy-safe telemetry for one onboarding model call or provider attempt.

    This table intentionally stores metadata and usage counts only. It never
    stores prompts, model responses, credentials, or source data.
    """

    __tablename__ = "onboarding_trace_events"

    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("onboarding_sessions.id", ondelete="CASCADE"), nullable=True, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    turn_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    parent_call_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    operation: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    attempt_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    context_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    usage_source: Mapped[str] = mapped_column(String(16), default="estimated", nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    error_category: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    error_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)
