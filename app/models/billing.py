from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Enum as SQLEnum, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.organizations import TimestampMixin, UUIDMixin


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class WalletStatus(str):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CLOSED = "closed"


class TransactionType(str):
    CREDIT = "credit"
    DEBIT = "debit"
    REFUND = "refund"


class Wallet(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "wallets"

    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False, unique=True, index=True)
    balance: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal("0.0000"), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="usd", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=WalletStatus.ACTIVE, nullable=False)


class WalletTransaction(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "wallet_transactions"

    wallet_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("wallets.id", ondelete="CASCADE"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    balance_before: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    balance_after: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    reference_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)


class PricingRule(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "pricing_rules"

    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    operation: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    price_per_unit: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="usd", nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)


class UsageLog(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "usage_logs"

    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    runtime_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    operation: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    embedding_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    vector_searches: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    storage_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    requests: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal("0.0000"), nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)


class Budget(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "budgets"

    user_id: Mapped[uuid.UUID] = mapped_column(unique=True, nullable=False, index=True)
    monthly_limit: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    current_spend: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal("0.0000"), nullable=False)
    warning_80_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    warning_90_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    limit_reached: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    auto_top_up_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    auto_top_up_threshold: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    auto_top_up_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    auto_top_up_stripe_payment_method_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
