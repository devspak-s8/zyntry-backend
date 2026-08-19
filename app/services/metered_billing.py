from __future__ import annotations

"""Concurrency-safe metered billing primitives.

This module is deliberately independent from payment/top-up providers.  It owns
the accounting that happens after a wallet has been funded.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_UP
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models.billing import (
    BillingLedger,
    BillingReservation,
    Budget,
    PricingRule,
    SpendingLimit,
    TransactionType,
    Wallet,
    WalletStatus,
)


MONEY_QUANTUM = Decimal("0.0001")
SPENDING_TRANSACTION_TYPES = (
    TransactionType.AI_INFERENCE,
    TransactionType.EMBEDDING,
    TransactionType.RERANKING,
    TransactionType.RAG,
    TransactionType.STORAGE,
    TransactionType.COMPUTE,
    TransactionType.INTEGRATION,
)


def money(value: Decimal | int | float | str) -> Decimal:
    return Decimal(str(value)).quantize(MONEY_QUANTUM, rounding=ROUND_UP)


class InsufficientBalanceError(Exception):
    def __init__(self, required: Decimal, available: Decimal) -> None:
        self.required = money(required)
        self.available = money(available)
        super().__init__(f"Insufficient balance: required {self.required}, available {self.available}")


class SpendingLimitError(Exception):
    def __init__(self, scope: str, limit: Decimal, projected: Decimal) -> None:
        self.scope = scope
        self.limit = money(limit)
        self.projected = money(projected)
        super().__init__(f"{scope} spending limit exceeded")


class PricingService:
    def __init__(self, session) -> None:
        self.session = session

    async def rules(self, provider: str, operation: str, model: str | None = None, at: datetime | None = None) -> list[PricingRule]:
        at = at or datetime.now(timezone.utc)
        stmt = select(PricingRule).where(
            PricingRule.provider.in_([provider, "*"]),
            PricingRule.operation == operation,
            PricingRule.active.is_(True),
            PricingRule.effective_from <= at,
            (PricingRule.effective_until.is_(None) | (PricingRule.effective_until > at)),
        )
        if model is not None:
            stmt = stmt.where((PricingRule.model == model) | PricingRule.model.is_(None))
        result = await self.session.execute(stmt.order_by(PricingRule.model.is_(None), PricingRule.version.desc(), PricingRule.created_at.desc()))
        return list(result.scalars().all())

    async def price(self, provider: str, model: str | None, operation: str, quantity: Decimal | int, *, at: datetime | None = None) -> tuple[Decimal, Decimal, PricingRule | None]:
        rules = await self.rules(provider, operation, model, at)
        rule = next((r for r in rules if r.model == model), None) or next((r for r in rules if r.model is None), None)
        if rule is None or quantity <= 0:
            return Decimal("0"), Decimal("0"), None
        provider_cost = money(rule.price_per_unit * Decimal(quantity))
        customer_cost = money(provider_cost * (Decimal("1") + Decimal(rule.markup or 0)))
        return customer_cost, provider_cost, rule

    async def calculate(self, provider: str, model: str | None, *, input_tokens: int = 0, output_tokens: int = 0, cached_tokens: int = 0, embedding_tokens: int = 0, vector_searches: int = 0, reranks: int = 0, storage_bytes: int = 0, requests: int = 1, resource_components: dict[str, Decimal | int] | None = None) -> dict[str, Any]:
        components: dict[str, dict[str, Any]] = {}
        for operation, quantity in (
            ("input_tokens", input_tokens),
            ("output_tokens", output_tokens),
            ("cached_tokens", cached_tokens),
            ("embeddings", embedding_tokens),
            ("vector_search", vector_searches),
            ("reranking", reranks),
            ("storage", storage_bytes),
            ("invoke", requests),
        ):
            if quantity <= 0:
                continue
            customer, provider_cost, rule = await self.price(provider, model, operation, quantity)
            if rule is not None:
                components[operation] = {
                    "quantity": quantity,
                    "customer_cost": customer,
                    "provider_cost": provider_cost,
                    "markup": customer - provider_cost,
                    "pricing_rule_id": str(rule.id),
                    "pricing_version": rule.version,
                }
        for operation, quantity in (resource_components or {}).items():
            if quantity <= 0 or operation in components:
                continue
            customer, provider_cost, rule = await self.price(provider, model, operation, quantity)
            if rule is not None:
                components[operation] = {
                    "quantity": quantity,
                    "customer_cost": customer,
                    "provider_cost": provider_cost,
                    "markup": customer - provider_cost,
                    "pricing_rule_id": str(rule.id),
                    "pricing_version": rule.version,
                }
        customer_total = sum((item["customer_cost"] for item in components.values()), Decimal("0"))
        provider_total = sum((item["provider_cost"] for item in components.values()), Decimal("0"))
        return {"amount": money(customer_total), "provider_cost": money(provider_total), "markup": money(customer_total - provider_total), "components": components}


class SpendingLimitService:
    def __init__(self, session) -> None:
        self.session = session

    @staticmethod
    def _period_start(period: str, now: datetime) -> datetime:
        if period == "daily":
            return now.replace(hour=0, minute=0, second=0, microsecond=0)
        if period == "monthly":
            return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return datetime(1970, 1, 1, tzinfo=timezone.utc)

    async def check(self, *, amount: Decimal, user_id: uuid.UUID, organization_id: uuid.UUID | None = None, project_id: uuid.UUID | None = None, runtime_id: uuid.UUID | None = None, api_key_id: uuid.UUID | None = None, now: datetime | None = None, exclude_reservation_id: uuid.UUID | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        scopes = [("user", user_id)]
        for scope, value in (("organization", organization_id), ("project", project_id), ("runtime", runtime_id), ("api_key", api_key_id)):
            if value is not None:
                scopes.append((scope, value))
        for scope, scope_id in scopes:
            result = await self.session.execute(select(SpendingLimit).where(SpendingLimit.scope_type == scope, SpendingLimit.scope_id == scope_id, SpendingLimit.active.is_(True)).with_for_update())
            for limit in result.scalars():
                start = self._period_start(limit.period, now)
                spent = await self.session.scalar(select(func.coalesce(func.sum(BillingLedger.amount), 0)).where(BillingLedger.status == "settled", BillingLedger.transaction_type.in_(SPENDING_TRANSACTION_TYPES), BillingLedger.created_at >= start, getattr(BillingLedger, f"{scope}_id") == scope_id))
                reservation_filters = [BillingReservation.status == "reserved", BillingReservation.created_at >= start, getattr(BillingReservation, f"{scope}_id") == scope_id]
                if exclude_reservation_id is not None:
                    reservation_filters.append(BillingReservation.id != exclude_reservation_id)
                reserved = await self.session.scalar(select(func.coalesce(func.sum(BillingReservation.estimated_amount), 0)).where(*reservation_filters))
                projected = Decimal(str(spent or 0)) + Decimal(str(reserved or 0)) + amount
                if projected > limit.amount:
                    raise SpendingLimitError(f"{scope} {limit.period}", limit.amount, projected)


class MeteredBillingService:
    def __init__(self, session) -> None:
        self.session = session
        self.pricing = PricingService(session)
        self.limits = SpendingLimitService(session)

    async def _wallet_for_update(self, user_id: uuid.UUID) -> Wallet:
        result = await self.session.execute(select(Wallet).where(Wallet.user_id == user_id).with_for_update())
        wallet = result.scalar_one_or_none()
        if wallet is None:
            wallet = Wallet(user_id=user_id, balance=Decimal("0"), currency="usd", status=WalletStatus.ACTIVE)
            self.session.add(wallet)
            await self.session.flush()
        return wallet

    async def _ledger(self, **data: Any) -> BillingLedger:
        row = BillingLedger(**data)
        self.session.add(row)
        await self.session.flush()
        return row

    async def reserve(self, *, user_id: uuid.UUID, amount: Decimal, request_id: str, idempotency_key: str, organization_id: uuid.UUID | None = None, project_id: uuid.UUID | None = None, runtime_id: uuid.UUID | None = None, api_key_id: uuid.UUID | None = None, resource_type: str = "runtime_execution", metadata: dict | None = None, ttl_seconds: int = 900) -> BillingReservation:
        amount = money(amount)
        if amount <= 0:
            raise ValueError("Reservation amount must be positive")
        existing = await self.session.scalar(select(BillingReservation).where(BillingReservation.idempotency_key == idempotency_key).with_for_update())
        if existing is not None:
            return existing
        await self.limits.check(amount=amount, user_id=user_id, organization_id=organization_id, project_id=project_id, runtime_id=runtime_id, api_key_id=api_key_id)
        wallet = await self._wallet_for_update(user_id)
        if wallet.status != WalletStatus.ACTIVE:
            raise ValueError(f"Wallet is {wallet.status}")
        if wallet.balance < amount:
            raise InsufficientBalanceError(amount, wallet.balance)
        wallet.balance -= amount
        wallet.reserved_balance += amount
        reservation = BillingReservation(wallet_id=wallet.id, user_id=user_id, organization_id=organization_id, project_id=project_id, runtime_id=runtime_id, api_key_id=api_key_id, request_id=request_id, idempotency_key=idempotency_key, estimated_amount=amount, currency=wallet.currency, resource_type=resource_type, expires_at=datetime.now(timezone.utc) + timedelta(seconds=max(1, ttl_seconds)), metadata_=metadata or {})
        self.session.add(reservation)
        try:
            await self.session.flush()
            await self._ledger(transaction_type=TransactionType.RESERVATION, user_id=user_id, organization_id=organization_id, project_id=project_id, runtime_id=runtime_id, api_key_id=api_key_id, request_id=request_id, idempotency_key=f"{idempotency_key}:reservation", resource_type=resource_type, resource_id=str(reservation.id), amount=amount, currency=wallet.currency, status="reserved", metadata_=metadata or {})
            await self.session.commit()
            return reservation
        except IntegrityError:
            await self.session.rollback()
            existing = await self.session.scalar(select(BillingReservation).where(BillingReservation.idempotency_key == idempotency_key))
            if existing is None:
                raise
            return existing

    async def settle(self, reservation_id: uuid.UUID, *, actual_amount: Decimal, provider_cost: Decimal = Decimal("0"), metadata: dict | None = None, transaction_type: str = TransactionType.AI_INFERENCE) -> BillingReservation:
        result = await self.session.execute(select(BillingReservation).where(BillingReservation.id == reservation_id).with_for_update())
        reservation = result.scalar_one()
        if reservation.status != "reserved":
            return reservation
        actual = money(actual_amount)
        if actual < 0:
            raise ValueError("Actual amount cannot be negative")
        wallet_result = await self.session.execute(select(Wallet).where(Wallet.id == reservation.wallet_id).with_for_update())
        wallet = wallet_result.scalar_one()
        if actual > reservation.estimated_amount:
            additional = actual - reservation.estimated_amount
            await self.limits.check(
                amount=additional,
                user_id=reservation.user_id,
                organization_id=reservation.organization_id,
                project_id=reservation.project_id,
                runtime_id=reservation.runtime_id,
                api_key_id=reservation.api_key_id,
                exclude_reservation_id=reservation.id,
            )
            if wallet.balance < additional:
                raise InsufficientBalanceError(actual, wallet.balance + reservation.estimated_amount)
            wallet.balance -= additional
            wallet.reserved_balance += additional
            reservation.estimated_amount += additional
        release = reservation.estimated_amount - actual
        wallet.reserved_balance -= reservation.estimated_amount
        wallet.balance += release
        wallet.total_spent += actual
        budget = await self.session.scalar(select(Budget).where(Budget.user_id == reservation.user_id).with_for_update())
        if budget is not None:
            budget.current_spend += actual
            if budget.monthly_limit is not None and budget.current_spend >= budget.monthly_limit:
                budget.limit_reached = True
        reservation.settled_amount = actual
        reservation.released_amount = release
        reservation.status = "settled"
        await self._ledger(transaction_type=transaction_type, user_id=reservation.user_id, organization_id=reservation.organization_id, project_id=reservation.project_id, runtime_id=reservation.runtime_id, api_key_id=reservation.api_key_id, request_id=reservation.request_id, idempotency_key=f"{reservation.idempotency_key}:settled", resource_type=reservation.resource_type, resource_id=str(reservation.id), amount=actual, currency=wallet.currency, provider_cost=money(provider_cost), platform_markup=money(actual - provider_cost), status="settled", metadata=metadata or {})
        if release > 0:
            await self._ledger(transaction_type=TransactionType.REVERSAL, user_id=reservation.user_id, organization_id=reservation.organization_id, project_id=reservation.project_id, runtime_id=reservation.runtime_id, api_key_id=reservation.api_key_id, request_id=reservation.request_id, idempotency_key=f"{reservation.idempotency_key}:release", resource_type="reservation", resource_id=str(reservation.id), amount=release, currency=wallet.currency, status="released", metadata={"reservation_id": str(reservation.id)})
        await self.session.commit()
        return reservation

    async def release(self, reservation_id: uuid.UUID, *, reason: str = "operation_failed") -> BillingReservation:
        result = await self.session.execute(select(BillingReservation).where(BillingReservation.id == reservation_id).with_for_update())
        reservation = result.scalar_one()
        if reservation.status != "reserved":
            return reservation
        wallet = (await self.session.execute(select(Wallet).where(Wallet.id == reservation.wallet_id).with_for_update())).scalar_one()
        wallet.reserved_balance -= reservation.estimated_amount
        wallet.balance += reservation.estimated_amount
        reservation.released_amount = reservation.estimated_amount
        reservation.status = "released"
        await self._ledger(transaction_type=TransactionType.REVERSAL, user_id=reservation.user_id, organization_id=reservation.organization_id, project_id=reservation.project_id, runtime_id=reservation.runtime_id, api_key_id=reservation.api_key_id, request_id=reservation.request_id, idempotency_key=f"{reservation.idempotency_key}:release", resource_type="reservation", resource_id=str(reservation.id), amount=reservation.estimated_amount, currency=wallet.currency, status="released", metadata={"reason": reason, "reservation_id": str(reservation.id)})
        await self.session.commit()
        return reservation

    async def expire_reservations(self, *, limit: int = 100, now: datetime | None = None) -> int:
        """Release abandoned reservations so reserved funds cannot become stranded."""
        now = now or datetime.now(timezone.utc)
        result = await self.session.execute(
            select(BillingReservation.id)
            .where(BillingReservation.status == "reserved", BillingReservation.expires_at <= now)
            .order_by(BillingReservation.expires_at.asc())
            .limit(limit)
        )
        ids = [row[0] for row in result.all()]
        released = 0
        for reservation_id in ids:
            await self.release(reservation_id, reason="reservation_expired")
            released += 1
        return released

    async def reconcile_wallet(self, user_id: uuid.UUID) -> dict[str, Any]:
        wallet = await self.session.scalar(select(Wallet).where(Wallet.user_id == user_id))
        if wallet is None:
            return {"ok": True, "wallet_id": None, "mismatches": []}
        settled_spend = await self.session.scalar(select(func.coalesce(func.sum(BillingLedger.amount), 0)).where(BillingLedger.user_id == user_id, BillingLedger.status == "settled", BillingLedger.transaction_type.in_([TransactionType.AI_INFERENCE, TransactionType.EMBEDDING, TransactionType.RERANKING, TransactionType.RAG, TransactionType.STORAGE, TransactionType.COMPUTE, TransactionType.INTEGRATION])))
        reserved = await self.session.scalar(select(func.coalesce(func.sum(BillingReservation.estimated_amount), 0)).where(BillingReservation.wallet_id == wallet.id, BillingReservation.status == "reserved"))
        expired = await self.session.scalar(select(func.count()).select_from(BillingReservation).where(BillingReservation.wallet_id == wallet.id, BillingReservation.status == "reserved", BillingReservation.expires_at <= datetime.now(timezone.utc)))
        mismatches: list[str] = []
        if money(wallet.reserved_balance) != money(reserved or 0):
            mismatches.append("reserved_balance")
        if money(wallet.total_spent) < money(settled_spend or 0):
            mismatches.append("total_spent")
        if wallet.balance < 0 or wallet.reserved_balance < 0:
            mismatches.append("negative_balance")
        if expired:
            mismatches.append("expired_reservations")
        return {"ok": not mismatches, "wallet_id": str(wallet.id), "mismatches": mismatches, "available_balance": wallet.balance, "reserved_balance": wallet.reserved_balance, "total_spent": wallet.total_spent, "expired_reservations": int(expired or 0)}
