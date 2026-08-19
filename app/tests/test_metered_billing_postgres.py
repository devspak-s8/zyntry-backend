"""Optional integration tests for PostgreSQL row locks and ledger triggers.

These tests are skipped in normal unit CI.  Set
``METERED_BILLING_TEST_DATABASE_URL`` to an isolated PostgreSQL database that
has the Alembic migrations applied to run them.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.billing import BillingLedger, Wallet
from app.models.users import User
from app.services.billing import BillingService
from app.services.metered_billing import InsufficientBalanceError, MeteredBillingService


pytestmark = pytest.mark.asyncio


def _database_url() -> str:
    return os.getenv("METERED_BILLING_TEST_DATABASE_URL", "")


@pytest.mark.skipif(not _database_url(), reason="METERED_BILLING_TEST_DATABASE_URL is not configured")
async def test_postgres_wallet_lock_allows_only_one_concurrent_reservation():
    engine = create_async_engine(_database_url(), pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    user_id = uuid.uuid4()
    async with sessions() as session:
        user = User(id=user_id, email=f"pg-{uuid.uuid4().hex}@example.com", name="PG test", is_active=True, email_verified=True)
        session.add(user)
        await session.commit()
        await BillingService(session).add_credit(user_id, Decimal("1"), "integration seed", reference_id=f"pg-topup-{uuid.uuid4()}")

    async def attempt(index: int):
        async with sessions() as session:
            try:
                return await MeteredBillingService(session).reserve(
                    user_id=user_id,
                    amount=Decimal("0.75"),
                    request_id=f"pg-req-{index}",
                    idempotency_key=f"pg-idem-{index}",
                )
            except InsufficientBalanceError:
                return None

    reservations = await asyncio.gather(attempt(1), attempt(2))
    assert sum(reservation is not None for reservation in reservations) == 1
    await engine.dispose()


@pytest.mark.skipif(not _database_url(), reason="METERED_BILLING_TEST_DATABASE_URL is not configured")
async def test_postgres_billing_ledger_is_immutable():
    engine = create_async_engine(_database_url(), pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session:
        ledger = await session.scalar(select(BillingLedger).limit(1))
        if ledger is None:
            pytest.skip("integration database has no billing ledger row")
        with pytest.raises(Exception, match="immutable"):
            await session.execute(update(BillingLedger).where(BillingLedger.id == ledger.id).values(amount=Decimal("999")))
            await session.commit()
        await session.rollback()
    await engine.dispose()
