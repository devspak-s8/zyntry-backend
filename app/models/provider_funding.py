from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.organizations import TimestampMixin, UUIDMixin


def utcnow() -> datetime:
    return datetime.now(UTC)


class ProviderFundingMode:
    MANUAL = "manual"
    PROVIDER_AUTO_RECHARGE = "provider_auto_recharge"
    ZYNTRY_MANAGED = "zyntry_managed"


class ProviderFundingStatus:
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    LOW = "low"
    AWAITING_RECHARGE = "awaiting_recharge"
    FUNDING_UNSUPPORTED = "funding_unsupported"
    ERROR = "error"
    DISABLED = "disabled"


class ProviderFundingAccount(Base, UUIDMixin, TimestampMixin):
    """Provider funding policy and an estimated balance.

    This is separate from customer wallets. Payment instruments are stored as
    references only; raw card data and provider secrets never belong here.
    """

    __tablename__ = "provider_funding_accounts"

    provider: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    account_label: Mapped[str] = mapped_column(String(255), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="usd", nullable=False)
    funding_mode: Mapped[str] = mapped_column(String(32), default=ProviderFundingMode.MANUAL, nullable=False)
    monitor_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    auto_top_up_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    current_balance: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    estimated_balance: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"), nullable=False)
    minimum_balance: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"), nullable=False)
    target_balance: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"), nullable=False)
    max_top_up: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"), nullable=False)
    daily_top_up_limit: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"), nullable=False)
    daily_top_up_total: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"), nullable=False)
    payment_method_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    external_account_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default=ProviderFundingStatus.UNKNOWN, nullable=False, index=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_top_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)


class ProviderFundingEvent(Base, UUIDMixin, TimestampMixin):
    """Auditable provider-cost, check, and funding event."""

    __tablename__ = "provider_funding_events"

    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("provider_funding_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"), nullable=False)
    balance_after: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)

    __table_args__ = (
        UniqueConstraint("provider", "request_id", "event_type", name="uq_provider_funding_request_event"),
    )
