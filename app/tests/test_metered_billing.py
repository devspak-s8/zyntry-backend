from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.models.billing import BillingReservation, SpendingLimit
from app.models.users import User
from app.services.billing import BillingService
from app.services.metered_billing import (
    InsufficientBalanceError,
    MeteredBillingService,
    SpendingLimitError,
)
from app.services.pricing_catalog import seed_pricing_catalog


async def _user(db_session):
    user = User(
        email=f"billing-{uuid.uuid4().hex}@example.com",
        name="Billing Test",
        is_active=True,
        is_superuser=False,
        email_verified=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.mark.asyncio
async def test_reservation_settlement_releases_unused_amount_and_is_idempotent(db_session):
    user = await _user(db_session)
    await BillingService(db_session).add_credit(user.id, Decimal("5"), "test topup", reference_id=f"topup-{uuid.uuid4()}")
    service = MeteredBillingService(db_session)
    reservation = await service.reserve(
        user_id=user.id,
        amount=Decimal("2"),
        request_id="req-1",
        idempotency_key="idem-1",
    )
    duplicate = await service.reserve(
        user_id=user.id,
        amount=Decimal("99"),
        request_id="req-1-retry",
        idempotency_key="idem-1",
    )
    assert duplicate.id == reservation.id
    await service.settle(reservation.id, actual_amount=Decimal("0.75"))
    settled = await service.settle(reservation.id, actual_amount=Decimal("1"))
    assert settled.status == "settled"
    wallet = await BillingService(db_session).get_wallet(user.id)
    assert wallet.balance == Decimal("4.25")
    assert wallet.reserved_balance == Decimal("0")
    assert wallet.total_spent == Decimal("0.75")


@pytest.mark.asyncio
async def test_reservation_release_on_failure_restores_balance(db_session):
    user = await _user(db_session)
    await BillingService(db_session).add_credit(user.id, Decimal("1"), "test topup", reference_id=f"topup-{uuid.uuid4()}")
    service = MeteredBillingService(db_session)
    reservation = await service.reserve(user_id=user.id, amount=Decimal("0.60"), request_id="req-2", idempotency_key="idem-2")
    await service.release(reservation.id, reason="provider_failed")
    wallet = await BillingService(db_session).get_wallet(user.id)
    assert wallet.balance == Decimal("1")
    assert wallet.reserved_balance == Decimal("0")
    assert wallet.total_spent == Decimal("0")


@pytest.mark.asyncio
async def test_reservation_rejects_insufficient_balance(db_session):
    user = await _user(db_session)
    service = MeteredBillingService(db_session)
    with pytest.raises(InsufficientBalanceError) as exc:
        await service.reserve(user_id=user.id, amount=Decimal("0.01"), request_id="req-3", idempotency_key="idem-3")
    assert exc.value.required == Decimal("0.0100")
    assert exc.value.available == Decimal("0.0000")


@pytest.mark.asyncio
async def test_daily_spending_limit_blocks_projected_charge(db_session):
    user = await _user(db_session)
    db_session.add(SpendingLimit(scope_type="user", scope_id=user.id, period="daily", amount=Decimal("0.50")))
    await db_session.commit()
    await BillingService(db_session).add_credit(user.id, Decimal("1"), "test topup", reference_id=f"topup-{uuid.uuid4()}")
    service = MeteredBillingService(db_session)
    with pytest.raises(SpendingLimitError):
        await service.reserve(user_id=user.id, amount=Decimal("0.51"), request_id="req-4", idempotency_key="idem-4")


@pytest.mark.asyncio
async def test_pricing_catalog_is_versioned_and_idempotent(db_session):
    first = await seed_pricing_catalog(db_session)
    second = await seed_pricing_catalog(db_session)
    assert first > 0
    assert second == 0
    estimate = await BillingService(db_session).calculate_cost(
        "openai", "gpt-4o-mini", "invoke", input_tokens=1000, output_tokens=1000
    )
    assert estimate > Decimal("0")
    resource = await BillingService(db_session).calculate_cost(
        "platform", "platform", "ocr", resource_components={"ocr": 2}
    )
    assert resource > Decimal("0")


@pytest.mark.asyncio
async def test_settlement_charges_additional_actual_cost(db_session):
    user = await _user(db_session)
    await BillingService(db_session).add_credit(user.id, Decimal("5"), "test topup", reference_id=f"topup-{uuid.uuid4()}")
    service = MeteredBillingService(db_session)
    reservation = await service.reserve(user_id=user.id, amount=Decimal("1"), request_id="req-over", idempotency_key="idem-over")
    await service.settle(reservation.id, actual_amount=Decimal("1.50"))
    wallet = await BillingService(db_session).get_wallet(user.id)
    assert wallet.balance == Decimal("3.50")
    assert wallet.total_spent == Decimal("1.50")


@pytest.mark.asyncio
async def test_expired_reservations_are_released(db_session):
    user = await _user(db_session)
    await BillingService(db_session).add_credit(user.id, Decimal("2"), "test topup", reference_id=f"topup-{uuid.uuid4()}")
    service = MeteredBillingService(db_session)
    reservation = await service.reserve(user_id=user.id, amount=Decimal("0.75"), request_id="req-expire", idempotency_key="idem-expire")
    reservation.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db_session.commit()
    assert await service.expire_reservations() == 1
    wallet = await BillingService(db_session).get_wallet(user.id)
    assert wallet.balance == Decimal("2")
    assert wallet.reserved_balance == Decimal("0")
