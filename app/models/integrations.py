from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.organizations import TimestampMixin, UUIDMixin


class RuntimeIntegration(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "runtime_integrations"

    runtime_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("runtimes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    integration_slug: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    connection_mode: Mapped[str] = mapped_column(
        String(64), default="zyntry_managed", nullable=False
    )
    enabled_capabilities: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    connection_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    connection_status: Mapped[str] = mapped_column(String(32), default="not_connected", nullable=False)
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("integration_connections.id", ondelete="SET NULL"), nullable=True
    )
    config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    __table_args__ = (
        UniqueConstraint("runtime_id", "integration_slug", name="uq_runtime_integration_slug"),
    )


class IntegrationConnection(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "integration_connections"

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    runtime_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("runtimes.id", ondelete="CASCADE"), nullable=True, index=True
    )
    integration_slug: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    connection_mode: Mapped[str] = mapped_column(
        String(64), default="zyntry_managed", nullable=False, index=True
    )
    end_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    auth_method: Mapped[str] = mapped_column(String(64), default="oauth2", nullable=False)
    encrypted_credentials: Mapped[str | None] = mapped_column(Text, nullable=True)
    scopes: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    refresh_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    last_synchronized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    health_status: Mapped[str] = mapped_column(String(32), default="healthy", nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)

    __table_args__ = (
        Index("ix_connections_runtime_enduser", "runtime_id", "end_user_id"),
        Index("ix_connections_user_slug", "user_id", "integration_slug"),
    )
