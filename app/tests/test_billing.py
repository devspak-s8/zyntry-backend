from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import Base
from app.models.billing import Budget, PricingRule, UsageLog, Wallet, WalletTransaction
from app.main import app


@pytest.fixture
async def auth_client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-Requested-With": "Zyntra"},
    ) as c:
        yield c


@pytest.mark.asyncio
async def test_wallet_creation_unauthorized(auth_client: AsyncClient):
    response = await auth_client.get("/api/v1/wallet")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_pricing_rules_list_unauthorized(auth_client: AsyncClient):
    response = await auth_client.get("/api/v1/wallet/pricing")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_estimate_cost_unauthorized(auth_client: AsyncClient):
    payload = {
        "provider": "openai",
        "model": "gpt-4o",
        "operation": "chat",
        "input_tokens": 100,
        "output_tokens": 200,
        "requests": 1,
    }
    response = await auth_client.post("/api/v1/wallet/estimate", json=payload)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_budget_unauthorized(auth_client: AsyncClient):
    response = await auth_client.get("/api/v1/wallet/budget")
    assert response.status_code == 401

    response = await auth_client.put("/api/v1/wallet/budget", json={"monthly_limit": 100})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_checkout_session_unauthorized(auth_client: AsyncClient):
    response = await auth_client.post("/api/v1/wallet/add-credits", json={"amount": 50})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_refund_unauthorized(auth_client: AsyncClient):
    response = await auth_client.post("/api/v1/wallet/refund", json={"transaction_id": str(uuid.uuid4()), "reason": "test"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_usage_logs_unauthorized(auth_client: AsyncClient):
    response = await auth_client.get("/api/v1/wallet/usage/logs")
    assert response.status_code == 401
