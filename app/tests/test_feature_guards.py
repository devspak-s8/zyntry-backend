from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.api.v1.billing.router import router as billing_router
from app.api.v1.features.dependencies import (
    require_action_feature,
    require_api_key_feature,
    require_feature,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "factory,principal",
    [
        (require_feature, SimpleNamespace(email="browser@example.com")),
        (require_api_key_feature, SimpleNamespace(email="sdk@example.com")),
    ],
)
async def test_user_feature_guards_return_enabled_principal(factory, principal) -> None:
    db = AsyncMock()
    dependency = factory("runtime_console")

    with patch(
        "app.api.v1.features.dependencies.FeatureFlagService.is_enabled",
        new=AsyncMock(return_value=True),
    ):
        assert await dependency(principal, db) is principal


@pytest.mark.asyncio
async def test_disabled_feature_guard_returns_403() -> None:
    dependency = require_feature("workflows")

    with patch(
        "app.api.v1.features.dependencies.FeatureFlagService.is_enabled",
        new=AsyncMock(return_value=False),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await dependency(SimpleNamespace(email="ordinary@example.com"), AsyncMock())

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_hybrid_action_guard_evaluates_authenticated_user() -> None:
    user = SimpleNamespace(email="actions@example.com")
    auth = SimpleNamespace(user=user)
    dependency = require_action_feature("actions")

    with patch(
        "app.api.v1.features.dependencies.FeatureFlagService.is_enabled",
        new=AsyncMock(return_value=True),
    ) as is_enabled:
        assert await dependency(auth, AsyncMock()) is auth

    assert is_enabled.await_args.args[1] is user


def test_payment_callback_remains_outside_feature_gating() -> None:
    callback = next(
        route for route in billing_router.routes if route.path == "/wallet/bachs-webhook"
    )

    assert callback.dependencies == []


def test_credit_purchase_requires_billing_and_purchase_features() -> None:
    checkout = next(
        route for route in billing_router.routes if route.path == "/wallet/add-credits"
    )

    assert len(checkout.dependencies) == 2
