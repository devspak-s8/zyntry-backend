from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.organizations import TimestampMixin, UUIDMixin


class ProviderConnection(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "provider_connections"

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    provider_name: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    api_key_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    encrypted_api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="inactive")
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    last_tested_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class OnboardingState(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "onboarding_states"

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    current_step: Mapped[str] = mapped_column(String(64), default="welcome")
    completed_steps: Mapped[list[str]] = mapped_column(JSONB, default=list)
    extra_data: Mapped[dict] = mapped_column(JSONB, default=dict)
