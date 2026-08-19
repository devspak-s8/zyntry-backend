from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.organizations import ORMModel


class WalletRead(ORMModel):
    id: uuid.UUID
    user_id: uuid.UUID
    balance: Decimal
    reserved_balance: Decimal = Decimal("0")
    total_spent: Decimal = Decimal("0")
    total_topups: Decimal = Decimal("0")
    currency: str
    status: str
    created_at: datetime
    updated_at: datetime


class WalletTransactionRead(ORMModel):
    id: uuid.UUID
    wallet_id: uuid.UUID
    type: str
    amount: Decimal
    balance_before: Decimal
    balance_after: Decimal
    reason: str
    reference_id: str | None
    metadata: dict
    created_at: datetime


class WalletTransactionCreate(BaseModel):
    amount: Decimal = Field(gt=0)
    reason: str = Field(min_length=1, max_length=255)
    reference_id: str | None = None
    metadata: dict | None = None


class AddCreditsRequest(BaseModel):
    amount: Decimal = Field(gt=0, description="Credit amount to add")
    metadata: dict | None = None


class RefundRequest(BaseModel):
    transaction_id: uuid.UUID
    reason: str = Field(min_length=1, max_length=255)


class PricingRuleRead(ORMModel):
    id: uuid.UUID
    provider: str
    operation: str
    model: str | None
    unit: str
    price_per_unit: Decimal
    currency: str
    active: bool
    cached_price_per_unit: Decimal | None = None
    markup: Decimal = Decimal("0")
    effective_from: datetime | None = None
    effective_until: datetime | None = None
    version: int = 1
    created_at: datetime
    updated_at: datetime


class PricingRuleCreate(BaseModel):
    provider: str = Field(min_length=1, max_length=64)
    operation: str = Field(min_length=1, max_length=64)
    model: str | None = None
    unit: str = Field(min_length=1, max_length=32)
    price_per_unit: Decimal = Field(ge=0)
    currency: str = Field(default="usd", min_length=3, max_length=3)
    active: bool = True
    cached_price_per_unit: Decimal | None = Field(default=None, ge=0)
    markup: Decimal = Field(default=Decimal("0"), ge=0)
    effective_from: datetime | None = None
    effective_until: datetime | None = None
    version: int = Field(default=1, ge=1)


class UsageLogRead(ORMModel):
    id: uuid.UUID
    user_id: uuid.UUID
    organization_id: uuid.UUID | None = None
    project_id: uuid.UUID | None
    runtime_id: uuid.UUID | None
    api_key_id: uuid.UUID | None = None
    request_id: str | None = None
    provider: str
    model: str
    operation: str
    input_tokens: int
    output_tokens: int
    cached_tokens: int = 0
    embedding_tokens: int
    vector_searches: int
    storage_bytes: int
    requests: int
    latency_ms: int | None
    cost: Decimal
    provider_cost: Decimal = Decimal("0")
    platform_markup: Decimal = Decimal("0")
    metadata: dict
    created_at: datetime


class UsageSummary(ORMModel):
    total_cost: Decimal
    total_requests: int
    total_input_tokens: int
    total_output_tokens: int
    total_embedding_tokens: int
    total_vector_searches: int
    total_storage_bytes: int
    total_latency_ms: int
    by_provider: dict[str, Decimal]
    by_model: dict[str, Decimal]
    by_operation: dict[str, Decimal]


class BudgetRead(ORMModel):
    id: uuid.UUID
    user_id: uuid.UUID
    monthly_limit: Decimal | None
    current_spend: Decimal
    warning_80_sent: bool
    warning_90_sent: bool
    limit_reached: bool
    auto_top_up_enabled: bool
    auto_top_up_threshold: Decimal | None
    auto_top_up_amount: Decimal | None
    created_at: datetime
    updated_at: datetime


class BudgetCreate(BaseModel):
    monthly_limit: Decimal = Field(gt=0)
    auto_top_up_enabled: bool = False
    auto_top_up_threshold: Decimal | None = Field(default=None, ge=0)
    auto_top_up_amount: Decimal | None = Field(default=None, gt=0)


class BudgetUpdate(BaseModel):
    monthly_limit: Decimal | None = Field(default=None, gt=0)
    auto_top_up_enabled: bool | None = None
    auto_top_up_threshold: Decimal | None = Field(default=None, ge=0)
    auto_top_up_amount: Decimal | None = Field(default=None, gt=0)


class EstimateCostRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=128)
    operation: str = Field(min_length=1, max_length=64)
    input_tokens: int = Field(ge=0, default=0)
    output_tokens: int = Field(ge=0, default=0)
    embedding_tokens: int = Field(ge=0, default=0)
    vector_searches: int = Field(ge=0, default=0)
    storage_bytes: int = Field(ge=0, default=0)
    requests: int = Field(ge=1, default=1)


class EstimateCostResponse(ORMModel):
    estimated_cost: Decimal
    currency: str
    breakdown: dict[str, Decimal]


class InsufficientCreditsError(ORMModel):
    error: str = "Insufficient Credits"
    required: Decimal
    balance: Decimal
    available_balance: Decimal | None = None


class SpendingLimitCreate(BaseModel):
    scope_type: str = Field(pattern="^(user|organization|project|runtime|api_key)$")
    scope_id: uuid.UUID
    period: str = Field(pattern="^(daily|monthly|lifetime)$")
    amount: Decimal = Field(gt=0)


class SpendingLimitRead(ORMModel):
    id: uuid.UUID
    scope_type: str
    scope_id: uuid.UUID
    period: str
    amount: Decimal
    active: bool


class BillingLedgerRead(ORMModel):
    id: uuid.UUID
    transaction_type: str
    user_id: uuid.UUID | None
    organization_id: uuid.UUID | None
    project_id: uuid.UUID | None
    runtime_id: uuid.UUID | None
    api_key_id: uuid.UUID | None
    request_id: str | None
    resource_type: str
    resource_id: str | None
    amount: Decimal
    currency: str
    provider_cost: Decimal
    platform_markup: Decimal
    status: str
    metadata: dict
    created_at: datetime


class CheckoutSessionRequest(BaseModel):
    amount: Decimal = Field(gt=0)
    currency: str = Field(default="usd", min_length=3, max_length=3)
    success_url: str | None = None
    cancel_url: str | None = None


class CheckoutSessionResponse(BaseModel):
    session_id: str
    url: str
    status: str | None = None


class BachsWebhookResponse(BaseModel):
    received: bool


class StripeWebhookResponse(BaseModel):
    received: bool
