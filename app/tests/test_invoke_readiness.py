import uuid
from types import SimpleNamespace
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from app.api.v1.invoke.router import _charge_invoke_if_billable, _is_runtime_ready


@pytest.mark.parametrize(
    ("status_value", "expected"),
    [
        ("active", True),
        ("ACTIVE", True),
        (" queued ", True),
        ("validating", True),
        ("failed", False),
        ("cancelled", False),
        (None, True),
    ],
)
def test_runtime_readiness_accepts_operational_states(status_value, expected):
    assert _is_runtime_ready(status_value) is expected


@pytest.mark.asyncio
async def test_zero_cost_invoke_does_not_create_wallet_debit():
    billing = SimpleNamespace(deduct_credit=AsyncMock())

    await _charge_invoke_if_billable(
        billing,
        user_id=uuid.uuid4(),
        amount=Decimal("0"),
        reason="Invoke",
        reference_id="req_test",
        metadata={},
    )

    billing.deduct_credit.assert_not_awaited()


@pytest.mark.asyncio
async def test_positive_cost_invoke_creates_wallet_debit():
    billing = SimpleNamespace(deduct_credit=AsyncMock())

    await _charge_invoke_if_billable(
        billing,
        user_id=uuid.uuid4(),
        amount=Decimal("0.01"),
        reason="Invoke",
        reference_id="req_test",
        metadata={},
    )

    billing.deduct_credit.assert_awaited_once()
