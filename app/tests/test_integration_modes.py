from __future__ import annotations

import uuid
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.users import User
from app.repositories import UnitOfWork
from app.schemas.integrations import (
    ConnectionDirectCreate,
    RuntimeIntegrationCreate,
)
from app.services.connections.service import ConnectionService
from app.services.integrations.service import IntegrationService
from app.services.runtimes import RuntimeService


@pytest.mark.asyncio
async def test_mode_a_zyntry_managed_connection(db_session: AsyncSession) -> None:
    """Mode A: Customer connects their own PostgreSQL/GitHub directly to Zyntry."""
    uow = UnitOfWork(db_session)
    runtime_service = RuntimeService(uow)
    integration_service = IntegrationService(uow)
    connection_service = ConnectionService(uow)

    # 1. Customer User
    customer = await uow.users.create(email="customer_corp@zyntry.space", name="Corp Admin")
    await uow.commit()

    # 2. Runtime with PostgreSQL capability enabled
    runtime = await uow.runtimes.create(
        user_id=customer.id,
        name="Company Analytics Runtime",
        provider="openai",
        model="gpt-4o",
    )
    await uow.commit()

    await integration_service.enable_runtime_integration(
        runtime_id=runtime.id,
        data=RuntimeIntegrationCreate(
            integration_slug="postgres",
            connection_mode="zyntry_managed",
            enabled_capabilities=["query", "schema_inspection"],
        ),
    )

    # 3. Customer connects their company database
    conn = await connection_service.create_direct_connection(
        user_id=customer.id,
        data=ConnectionDirectCreate(
            integration_slug="postgres",
            connection_mode="zyntry_managed",
            runtime_id=str(runtime.id),
            display_name="Production DB",
            auth_method="connection_string",
            credentials={"connection_string": "postgresql://admin:secret_pass@db.corp.internal:5432/main"},
        ),
    )
    assert conn.status == "active"
    assert conn.encrypted_credentials is not None
    assert "secret_pass" not in conn.encrypted_credentials  # Must be encrypted!

    # 4. Runtime execution retrieves authorized decrypted credentials
    exec_ctx = await connection_service.get_connection_for_execution(
        runtime_id=runtime.id,
        integration_slug="postgres",
    )
    assert exec_ctx["credentials"]["connection_string"] == "postgresql://admin:secret_pass@db.corp.internal:5432/main"
    assert "query" in exec_ctx["enabled_capabilities"]


@pytest.mark.asyncio
async def test_mode_b_byo_user_connections_and_isolation(db_session: AsyncSession) -> None:
    """Mode B: Customer enables capability on runtime; end users connect isolated accounts."""
    uow = UnitOfWork(db_session)
    integration_service = IntegrationService(uow)
    connection_service = ConnectionService(uow)

    # 1. Customer develops an app
    developer = await uow.users.create(email="developer@saas.com", name="SaaS Developer")
    await uow.commit()

    runtime = await uow.runtimes.create(
        user_id=developer.id,
        name="Dev SaaS Runtime",
        provider="openai",
        model="gpt-4o",
    )
    await uow.commit()

    # Enable GitHub capability in Mode B (end_user_oauth)
    await integration_service.enable_runtime_integration(
        runtime_id=runtime.id,
        data=RuntimeIntegrationCreate(
            integration_slug="github",
            connection_mode="end_user_oauth",
            enabled_capabilities=["repository_search", "file_retrieval", "issue_access"],
        ),
    )

    # Note: Developer has NOT provided any personal GitHub credential!
    dev_managed = await uow.integration_connections.get_zyntry_managed(developer.id, "github")
    assert dev_managed is None

    # 2. End User Alice connects her GitHub account
    alice_conn = await connection_service.create_direct_connection(
        user_id=None,
        data=ConnectionDirectCreate(
            integration_slug="github",
            connection_mode="end_user_oauth",
            runtime_id=str(runtime.id),
            end_user_id="alice_uuid_101",
            display_name="Alice's GitHub (alice_org)",
            auth_method="oauth2",
            credentials={"access_token": "gho_alice_token_secret_123"},
        ),
    )

    # 3. End User Bob connects his GitHub account
    bob_conn = await connection_service.create_direct_connection(
        user_id=None,
        data=ConnectionDirectCreate(
            integration_slug="github",
            connection_mode="end_user_oauth",
            runtime_id=str(runtime.id),
            end_user_id="bob_uuid_202",
            display_name="Bob's GitHub (bob_corp)",
            auth_method="oauth2",
            credentials={"access_token": "gho_bob_token_secret_456"},
        ),
    )

    # 4. Verification of Strict Isolation:
    # Query for Alice:
    alice_ctx = await connection_service.get_connection_for_execution(
        runtime_id=runtime.id,
        integration_slug="github",
        end_user_id="alice_uuid_101",
    )
    assert alice_ctx["credentials"]["access_token"] == "gho_alice_token_secret_123"

    # Query for Bob:
    bob_ctx = await connection_service.get_connection_for_execution(
        runtime_id=runtime.id,
        integration_slug="github",
        end_user_id="bob_uuid_202",
    )
    assert bob_ctx["credentials"]["access_token"] == "gho_bob_token_secret_456"

    # Query for Charlie (who hasn't connected GitHub):
    with pytest.raises(PermissionError, match="No active authorized connection"):
        await connection_service.get_connection_for_execution(
            runtime_id=runtime.id,
            integration_slug="github",
            end_user_id="charlie_uuid_303",
        )

    # Missing end_user_id in Mode B raises ValueError
    with pytest.raises(ValueError, match="end_user_id is required"):
        await connection_service.get_connection_for_execution(
            runtime_id=runtime.id,
            integration_slug="github",
            end_user_id=None,
        )
