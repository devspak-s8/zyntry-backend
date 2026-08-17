from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import UnitOfWork
from app.schemas.integrations import (
    ConnectionAuthorizeRequest,
    ConnectionDirectCreate,
    RuntimeIntegrationCreate,
)
from app.services.connections.service import ConnectionService
from app.services.integrations.service import IntegrationService
from app.services.security.secrets import SecretManager, default_secret_manager


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
async def test_connection_oauth_authorize_and_callback(db_session: AsyncSession) -> None:
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
