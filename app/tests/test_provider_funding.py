from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.provider_funding import ProviderFundingMode, ProviderFundingStatus
from app.services.provider_funding import ProviderFundingService


@pytest.mark.asyncio
async def test_provider_cost_reduces_estimated_balance_and_is_idempotent(db_session):
    service = ProviderFundingService(db_session)
    account = await service.configure(
        "openai",
        current_balance=Decimal("100"),
        minimum_balance=Decimal("50"),
        target_balance=Decimal("200"),
        max_top_up=Decimal("150"),
        daily_top_up_limit=Decimal("300"),
    )
    await service.record_provider_cost("openai", Decimal("60"), request_id="req-1")
    await service.record_provider_cost("openai", Decimal("60"), request_id="req-1")
    await db_session.refresh(account)
    assert account.estimated_balance == Decimal("40.000000")
    assert account.status == ProviderFundingStatus.LOW


@pytest.mark.asyncio
async def test_provider_auto_recharge_is_flagged_for_provider_side_recharge(db_session):
    service = ProviderFundingService(db_session)
    account = await service.configure(
        "gemini",
        funding_mode=ProviderFundingMode.PROVIDER_AUTO_RECHARGE,
        auto_top_up_enabled=True,
        current_balance=Decimal("4"),
        minimum_balance=Decimal("5"),
        target_balance=Decimal("20"),
        max_top_up=Decimal("16"),
        daily_top_up_limit=Decimal("50"),
    )
    result = await service.check_account(account)
    assert result["status"] == ProviderFundingStatus.AWAITING_RECHARGE
    assert "provider-side auto-recharge" in result["last_error"].lower()
