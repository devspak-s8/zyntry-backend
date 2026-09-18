from __future__ import annotations

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.repositories import UnitOfWork
from app.schemas.integrations import (
    ConnectionAuthorizeRequest,
    RuntimeIntegrationCreate,
    RuntimeIntegrationUpdate,
)
from app.services.connections.service import ConnectionService
from app.services.integrations.service import IntegrationService
from app.services.security.secrets import SecretManager


@pytest.mark.asyncio
async def test_secret_manager_operations() -> None:
    sm = SecretManager()
    plain = "my-ultra-secret-api-token-12345"

    encrypted = sm.encrypt(plain)
    assert encrypted.startswith("ENCV1:")
    assert plain not in encrypted

    decrypted = sm.decrypt(encrypted)
    assert decrypted == plain

    # Redaction
    sensitive_dict = {
        "user": "alice",
        "api_key": "sk_live_1234567890abcdef",
        "password": "supersecretpassword",
        "nested": {"token": "ghp_secrettoken12345", "public_id": "pub_123"},
    }
    redacted = sm.redact(sensitive_dict)
    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["password"] == "[REDACTED]"
    assert redacted["nested"]["token"] == "[REDACTED]"
    assert redacted["nested"]["public_id"] == "pub_123"
    assert redacted["user"] == "alice"


@pytest.mark.asyncio
async def test_connection_oauth_authorize_and_callback(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _TokenResponse:
        status_code = 200

        @staticmethod
        def json() -> dict[str, str | int]:
            return {
                "access_token": "provider-access-token",
                "refresh_token": "provider-refresh-token",
                "expires_in": 3600,
                "scope": "channels:read channels:history search:read chat:write",
                "token_type": "Bearer",
            }

    class _TokenClient:
        async def __aenter__(self) -> _TokenClient:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def post(self, *_: object, **__: object) -> _TokenResponse:
            return _TokenResponse()

    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: _TokenClient())
    monkeypatch.setattr(settings, "SLACK_CLIENT_ID", "test-slack-client")
    monkeypatch.setattr(settings, "SLACK_CLIENT_SECRET", "test-slack-secret")

    uow = UnitOfWork(db_session)
    connection_service = ConnectionService(uow)
    integration_service = IntegrationService(uow)

    user = await uow.users.create(email="oauth_tester@zyntry.space", name="OAuth Tester")
    await uow.commit()

    runtime = await uow.runtimes.create(
        user_id=user.id,
        name="OAuth Test Runtime",
        provider="openai",
        model="gpt-4o",
    )
    await uow.commit()

    await integration_service.enable_runtime_integration(
        runtime_id=runtime.id,
        data=RuntimeIntegrationCreate(
            integration_slug="slack",
            connection_mode="zyntry_managed",
            enabled_capabilities=["message_search", "send_messages"],
        ),
    )

    # 1. Authorize connection flow
    auth_resp = await connection_service.authorize(
        integration_slug="slack",
        user_id=user.id,
        data=ConnectionAuthorizeRequest(
            runtime_id=str(runtime.id),
            connection_mode="zyntry_managed",
            display_name="Slack Company Workspace",
        ),
    )
    assert auth_resp.requires_authorization is True
    assert auth_resp.state is not None
    assert "https://slack.com/oauth" in auth_resp.url

    # 2. Callback
    conn = await connection_service.handle_callback(
        integration_slug="slack",
        code="fake_slack_auth_code_99",
        state=auth_resp.state,
        expected_user_id=user.id,
    )
    assert conn.status == "active"
    assert conn.integration_slug == "slack"
    assert conn.connection_mode == "zyntry_managed"

    # 3. Connection retrieval and execution
    exec_data = await connection_service.get_connection_for_execution(
        runtime_id=runtime.id,
        integration_slug="slack",
    )
    assert "access_token" in exec_data["credentials"]

    # 4. Revocation
    await connection_service.revoke_connection(conn.id)
    with pytest.raises(PermissionError, match="No active authorized connection"):
        await connection_service.get_connection_for_execution(
            runtime_id=runtime.id,
            integration_slug="slack",
        )


@pytest.mark.asyncio
async def test_existing_managed_connection_is_linked_to_runtime(
    db_session: AsyncSession,
) -> None:
    """Reusing an account-scoped OAuth connection must satisfy the runtime."""
    uow = UnitOfWork(db_session)
    connection_service = ConnectionService(uow)
    integration_service = IntegrationService(uow)

    user = await uow.users.create(email="managed_connection@zyntry.space", name="Managed User")
    runtime = await uow.runtimes.create(
        user_id=user.id,
        name="Managed Connection Runtime",
        provider="openai",
        model="gpt-4o",
    )
    await uow.commit()

    await integration_service.enable_runtime_integration(
        runtime_id=runtime.id,
        data=RuntimeIntegrationCreate(
            integration_slug="github",
            connection_mode="zyntry_managed",
            enabled_capabilities=["repository_search"],
        ),
    )

    existing = await uow.integration_connections.create(
        user_id=user.id,
        runtime_id=None,
        integration_slug="github",
        connection_mode="zyntry_managed",
        display_name="Company GitHub",
        auth_method="oauth2",
        encrypted_credentials="ENCV1:existing-github-credentials",
        scopes=["repo"],
        status="active",
        health_status="healthy",
    )
    await uow.commit()

    result = await connection_service.authorize(
        integration_slug="github",
        user_id=user.id,
        data=ConnectionAuthorizeRequest(
            runtime_id=str(runtime.id),
            connection_mode="zyntry_managed",
        ),
    )

    assert result.requires_authorization is False
    assert result.connection_id == str(existing.id)

    runtime_integration = await uow.runtime_integrations.get_by_runtime_and_slug(
        runtime.id, "github"
    )
    assert runtime_integration is not None
    assert runtime_integration.connection_id == existing.id
    assert runtime_integration.connection_status == "connected"
    assert runtime_integration.connection_required is False

    listed = await connection_service.list_connections(
        user_id=user.id,
        runtime_id=str(runtime.id),
        integration_slug="github",
    )
    assert [connection.id for connection in listed] == [existing.id]


@pytest.mark.asyncio
async def test_stale_runtime_connection_link_is_cleared_when_policy_is_reenabled(
    db_session: AsyncSession,
) -> None:
    """A revoked or mismatched connection must never remain reported as connected."""
    uow = UnitOfWork(db_session)
    integration_service = IntegrationService(uow)

    user = await uow.users.create(email="stale_link@zyntry.space", name="Stale Link User")
    runtime = await uow.runtimes.create(
        user_id=user.id,
        name="Stale Link Runtime",
        provider="openai",
        model="gpt-4o",
    )
    stale_connection = await uow.integration_connections.create(
        user_id=user.id,
        runtime_id=runtime.id,
        integration_slug="github",
        connection_mode="zyntry_managed",
        display_name="Revoked GitHub",
        auth_method="oauth2",
        encrypted_credentials="ENCV1:revoked-github-credentials",
        scopes=["repo"],
        status="revoked",
        health_status="unhealthy",
    )
    await uow.commit()

    policy = await integration_service.enable_runtime_integration(
        runtime_id=runtime.id,
        data=RuntimeIntegrationCreate(
            integration_slug="github",
            connection_mode="zyntry_managed",
            enabled_capabilities=["repository_search"],
        ),
    )
    await uow.runtime_integrations.update(
        policy,
        connection_id=stale_connection.id,
        connection_required=False,
        connection_status="connected",
    )
    await uow.commit()

    refreshed = await integration_service.enable_runtime_integration(
        runtime_id=runtime.id,
        data=RuntimeIntegrationCreate(
            integration_slug="github",
            connection_mode="zyntry_managed",
            enabled_capabilities=["repository_search"],
        ),
    )

    assert refreshed.connection_id is None
    assert refreshed.connection_required is True
    assert refreshed.connection_status == "connection_required"


@pytest.mark.asyncio
async def test_connection_mode_switch_preserves_company_connection_for_rollback(
    db_session: AsyncSession,
) -> None:
    uow = UnitOfWork(db_session)
    service = IntegrationService(uow)
    user = await uow.users.create(
        email="mode_switch@zyntry.space",
        name="Mode Switch User",
    )
    runtime = await uow.runtimes.create(
        user_id=user.id,
        name="Mode Switch Runtime",
        provider="openai",
        model="gpt-4o",
    )
    policy = await service.enable_runtime_integration(
        runtime.id,
        RuntimeIntegrationCreate(
            integration_slug="github",
            connection_mode="zyntry_managed",
            enabled_capabilities=["repository_search"],
        ),
    )
    company_connection = await uow.integration_connections.create(
        user_id=user.id,
        runtime_id=runtime.id,
        integration_slug="github",
        connection_mode="zyntry_managed",
        display_name="Company GitHub",
        auth_method="oauth2",
        encrypted_credentials="ENCV1:company-github",
        scopes=["repo"],
        status="active",
        health_status="healthy",
    )
    await uow.runtime_integrations.update(
        policy,
        connection_id=company_connection.id,
        connection_required=False,
        connection_status="connected",
    )
    await uow.commit()

    switched = await service.update_runtime_integration(
        runtime.id,
        "github",
        RuntimeIntegrationUpdate(connection_mode="end_user_oauth"),
    )
    assert switched.connection_mode == "end_user_oauth"
    assert switched.connection_id is None
    assert switched.connection_status == "ready_for_end_users"
    assert (switched.config or {}).get("previous_connection_id") == str(company_connection.id)
    assert (await uow.integration_connections.get(company_connection.id)).status == "active"

    restored = await service.update_runtime_integration(
        runtime.id,
        "github",
        RuntimeIntegrationUpdate(connection_mode="zyntry_managed"),
    )
    assert restored.connection_mode == "zyntry_managed"
    assert restored.connection_id == company_connection.id
    assert restored.connection_status == "connected"
