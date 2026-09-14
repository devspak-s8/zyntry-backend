from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.v1.billing.router import billing_analytics, list_usage_logs
from app.main import app
from app.models.billing import UsageLog
from app.models.organizations import Organization
from app.models.projects import Project
from app.models.runtimes import Runtime
from app.models.users import User


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


@pytest.mark.asyncio
async def test_billing_analytics_uses_usage_dimensions_and_resource_names(db_session):
    organization = Organization(name="Acme", slug=f"acme-{uuid.uuid4().hex}")
    db_session.add(organization)
    await db_session.flush()
    user = User(
        email=f"analytics-{uuid.uuid4().hex}@example.com",
        name="Analytics Test",
        organization_id=organization.id,
        is_active=True,
        email_verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    project = Project(
        name="Support Console",
        slug=f"support-{uuid.uuid4().hex}",
        organization_id=organization.id,
    )
    db_session.add(project)
    await db_session.flush()
    runtime = Runtime(
        name="Support Runtime",
        user_id=user.id,
        organization_id=organization.id,
        project_id=project.id,
    )
    db_session.add(runtime)
    await db_session.flush()
    db_session.add(
        UsageLog(
            user_id=user.id,
            organization_id=organization.id,
            project_id=project.id,
            runtime_id=runtime.id,
            request_id="req-analytics",
            provider="google",
            model="gemini-2.5-flash",
            operation="invoke",
            input_tokens=8,
            output_tokens=3,
            requests=1,
            cost=Decimal("0.0001"),
        )
    )
    await db_session.commit()

    result = await billing_analytics(user, db_session, days=30)

    assert result["by_provider"][0]["provider"] == "google"
    assert result["by_model"][0]["model"] == "gemini-2.5-flash"
    assert result["by_operation"][0]["operation"] == "invoke"
    assert result["by_project"][0]["project"] == "Support Console"
    assert result["by_runtime"][0]["runtime"] == "Support Runtime"
    assert result["daily"][0]["date"]


@pytest.mark.asyncio
async def test_billing_analytics_accepts_short_hour_window(db_session):
    """The dashboard can query recent usage without widening to a full day."""
    user = User(
        email=f"analytics-hours-{uuid.uuid4().hex}@example.com",
        name="Short Window Test",
        is_active=True,
        email_verified=True,
    )
    db_session.add(user)
    await db_session.flush()

    db_session.add(
        UsageLog(
            user_id=user.id,
            request_id="req-hours",
            provider="google",
            model="gemini-2.5-flash",
            operation="invoke",
            input_tokens=2,
            output_tokens=1,
            requests=1,
            cost=Decimal("0.0001"),
        )
    )
    await db_session.commit()

    result = await billing_analytics(user, db_session, days=30, hours=1)

    assert result["period_hours"] == 1
    assert result["period_days"] == 30
    assert result["by_provider"][0]["provider"] == "google"


@pytest.mark.asyncio
async def test_usage_logs_can_be_scoped_to_runtime_and_project(db_session):
    organization = Organization(name="Usage Scope", slug=f"usage-{uuid.uuid4().hex}")
    db_session.add(organization)
    await db_session.flush()
    user = User(
        email=f"usage-{uuid.uuid4().hex}@example.com",
        name="Usage Scope",
        organization_id=organization.id,
        is_active=True,
        email_verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    project = Project(
        name="Scoped Project",
        slug=f"scoped-{uuid.uuid4().hex}",
        organization_id=organization.id,
    )
    db_session.add(project)
    await db_session.flush()
    selected_runtime = Runtime(
        name="Selected Runtime",
        user_id=user.id,
        organization_id=organization.id,
        project_id=project.id,
    )
    other_runtime = Runtime(
        name="Other Runtime",
        user_id=user.id,
        organization_id=organization.id,
    )
    db_session.add_all([selected_runtime, other_runtime])
    await db_session.flush()
    db_session.add_all([
        UsageLog(
            user_id=user.id,
            organization_id=organization.id,
            project_id=project.id,
            runtime_id=selected_runtime.id,
            request_id="req-selected",
            provider="google",
            model="gemini-2.5-flash",
            operation="invoke",
            requests=1,
            cost=Decimal("0.0001"),
        ),
        UsageLog(
            user_id=user.id,
            organization_id=organization.id,
            runtime_id=other_runtime.id,
            request_id="req-other",
            provider="openai",
            model="gpt-4o-mini",
            operation="invoke",
            requests=1,
            cost=Decimal("0.0001"),
        ),
    ])
    await db_session.commit()

    result = await list_usage_logs(
        current_user=user,
        db=db_session,
        limit=50,
        offset=0,
        runtime_id=selected_runtime.id,
        project_id=project.id,
        since=None,
    )

    assert len(result) == 1
    assert result[0].request_id == "req-selected"
    assert result[0].runtime_id == selected_runtime.id
