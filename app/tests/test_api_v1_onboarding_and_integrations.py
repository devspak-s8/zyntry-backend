from __future__ import annotations

import uuid
from unittest.mock import AsyncMock
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.services.feature_flags import FeatureFlagService
from app.api.v1.dependencies import get_current_user
from app.main import app as fastapi_app
from app.models.users import User
from app.repositories import UnitOfWork


@pytest.mark.asyncio
async def test_api_v1_onboarding_and_integrations_routes(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Allow all feature guards in test environment
    monkeypatch.setattr(FeatureFlagService, "is_enabled", AsyncMock(return_value=True))

    uow = UnitOfWork(db_session)
    user = await uow.users.create(email="api_tester@zyntry.space", name="API Tester", is_active=True)
    await uow.commit()

    # Override current user
    fastapi_app.dependency_overrides[get_current_user] = lambda: user

    try:
        # 1. Integrations Catalog API
        resp = await client.get("/api/v1/integrations")
        assert resp.status_code == 200
        catalog = resp.json()
        integrations = catalog.get("integrations", catalog) if isinstance(catalog, dict) else catalog
        assert len(integrations) >= 9
        slugs = {i["slug"] for i in integrations}
        assert "github" in slugs
        assert "slack" in slugs
        assert "postgresql" in slugs

        # Get single integration
        resp_gh = await client.get("/api/v1/integrations/github")
        assert resp_gh.status_code == 200
        assert resp_gh.json()["slug"] == "github"
        assert "end_user_oauth" in resp_gh.json()["connection_modes"]

        # 2. Chat Onboarding Flow via API
        # Step A: Start Session
        resp_sess = await client.post(
            "/api/v1/onboarding/session",
            json={"initial_prompt": "I want to build a customer support AI bot"},
        )
        assert resp_sess.status_code == 201
        session_data = resp_sess.json()
        session_id = session_data["id"]
        assert session_data["state"] == "discovering_application_type"

        # Step B: Choose Mode B
        resp_msg1 = await client.post(
            "/api/v1/onboarding/message",
            json={
                "session_id": session_id,
                "message": "End users will connect their own accounts (Mode B)",
            },
        )
        assert resp_msg1.status_code == 200
        assert resp_msg1.json()["state"] == "selecting_integrations"

        # Step C: Select GitHub and Slack
        resp_msg2 = await client.post(
            "/api/v1/onboarding/message",
            json={
                "session_id": session_id,
                "message": "Enable GitHub and Slack integrations",
            },
        )
        assert resp_msg2.status_code == 200
        assert resp_msg2.json()["state"] == "configuring_runtime"

        # Step D: Configure Model
        resp_msg3 = await client.post(
            "/api/v1/onboarding/message",
            json={
                "session_id": session_id,
                "message": "Use GPT-4o with balanced routing",
            },
        )
        assert resp_msg3.status_code == 200
        assert resp_msg3.json()["state"] == "confirming_configuration"
        assert resp_msg3.json()["proposed_runtime"] is not None

        # Step E: Complete Onboarding & Provision Runtime
        resp_comp = await client.post(
            "/api/v1/onboarding/complete",
            json={
                "session_id": session_id,
                "runtime_name": "API Provisioned Support Runtime",
                "environment": "development",
            },
        )
        assert resp_comp.status_code == 200
        comp_data = resp_comp.json()
        assert comp_data["status"] == "preconfigured"
        runtime_id = comp_data["runtime_id"]

        # 3. Runtimes API
        # List runtimes for current user
        resp_runtimes = await client.get("/api/v1/runtimes")
        assert resp_runtimes.status_code == 200
        runtimes_list = resp_runtimes.json()
        assert any(r["id"] == runtime_id for r in runtimes_list)

        # Get runtime details
        resp_r = await client.get(f"/api/v1/runtimes/{runtime_id}")
        assert resp_r.status_code == 200
        assert resp_r.json()["name"] == "API Provisioned Support Runtime"

        # List integrations on runtime
        resp_ri = await client.get(f"/api/v1/runtimes/{runtime_id}/integrations")
        assert resp_ri.status_code == 200
        assert len(resp_ri.json()) == 2

        # Enable Postgres capability dynamically on the runtime
        resp_enable_pg = await client.post(
            f"/api/v1/runtimes/{runtime_id}/integrations",
            json={
                "integration_slug": "postgres",
                "connection_mode": "zyntry_managed",
                "enabled_capabilities": ["query", "schema_inspection"],
            },
        )
        assert resp_enable_pg.status_code == 201

        # 4. Decoupled API Key Creation for Runtime
        resp_key = await client.post(
            f"/api/v1/runtimes/{runtime_id}/api-keys",
            json={
                "name": "Frontend Webhook Key",
                "environment": "development",
                "scopes": ["read", "write"],
            },
        )
        assert resp_key.status_code == 201
        key_data = resp_key.json()
        assert key_data["runtime_id"] == runtime_id
        assert key_data["key"].startswith("sk_test_")
        key_id = key_data["id"]

        # Rotate API Key
        resp_rot = await client.post(f"/api/v1/apikeys/{key_id}/rotate")
        assert resp_rot.status_code == 200
        assert resp_rot.json()["raw_key"].startswith("sk_test_")

        # 5. Direct Connection API (Mode A & Mode B)
        resp_conn = await client.post(
            "/api/v1/connections",
            json={
                "integration_slug": "postgres",
                "connection_mode": "zyntry_managed",
                "runtime_id": runtime_id,
                "display_name": "Read Replica DB",
                "auth_method": "connection_string",
                "credentials": {"connection_string": "postgresql://usr:pwd@db:5432/app"},
            },
        )
        assert resp_conn.status_code == 201
        conn_data = resp_conn.json()
        assert conn_data["status"] == "active"
        conn_id = conn_data["id"]

        # List connections (verify credentials are not exposed)
        resp_conns = await client.get(f"/api/v1/connections?runtime_id={runtime_id}")
        assert resp_conns.status_code == 200
        assert len(resp_conns.json()) >= 1
        for c in resp_conns.json():
            assert "pwd" not in str(c)

        # Delete connection
        resp_del = await client.delete(f"/api/v1/connections/{conn_id}")
        assert resp_del.status_code == 204

    finally:
        fastapi_app.dependency_overrides.pop(get_current_user, None)
