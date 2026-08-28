from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.runtimes.router import delete_runtime, list_runtimes, update_runtime
from app.repositories import UnitOfWork
from app.schemas.apikeys import ApiKeyCreate
from app.schemas.integrations import (
    RuntimeIntegrationCreate,
    RuntimeIntegrationUpdate,
)
from app.schemas.runtimes import RuntimeCreate, RuntimeUpdate
from app.services.apikeys import ApiKeyService
from app.services.integrations.service import IntegrationService
from app.services.runtimes import RuntimeService


@pytest.mark.asyncio
async def test_runtime_listing_is_isolated_for_a_first_time_user(
    db_session: AsyncSession,
) -> None:
    uow = UnitOfWork(db_session)
    new_user = await uow.users.create(email="new_user@zyntry.space", name="New User")
    other_user = await uow.users.create(email="other_user@zyntry.space", name="Other User")
    await uow.commit()

    other_runtime = await RuntimeService(uow).get_or_create(
        RuntimeCreate(name="Other User Runtime"),
        default_user_id=other_user.id,
    )

    result = await list_runtimes(
        current_user=new_user,
        organization_id=None,
        project_id=None,
        db=db_session,
    )

    assert result == []
    assert all(str(runtime.id) != other_runtime["id"] for runtime in result)


@pytest.mark.asyncio
async def test_user_first_runtime_and_capabilities(db_session: AsyncSession) -> None:
    uow = UnitOfWork(db_session)
    runtime_service = RuntimeService(uow)
    integration_service = IntegrationService(uow)
    apikey_service = ApiKeyService(db_session)

    # 1. User without organization
    user = await uow.users.create(email="independent_dev@zyntry.space", name="Solo Builder")
    await uow.commit()

    # 2. Create Runtime directly
    runtime_data = await runtime_service.get_or_create(
        data=RuntimeCreate(
            name="Developer Workspace Runtime",
            environment="staging",
            provider="openai",
            model="gpt-4o",
            routing_strategy="fastest",
            fallback_models=["claude-3-5-sonnet-20241022", "deepseek-chat"],
            security_policies={"data_retention_days": 30},
            system_instructions="You are a helpful coding assistant with access to GitHub and Notion.",
        ),
        default_user_id=user.id,
    )
    assert runtime_data["user_id"] == str(user.id)
    assert runtime_data["name"] == "Developer Workspace Runtime"
    assert runtime_data["environment"] == "staging"
    assert runtime_data["routing_strategy"] == "fastest"
    assert runtime_data["fallback_models"] == ["claude-3-5-sonnet-20241022", "deepseek-chat"]
    runtime_id = uuid.UUID(runtime_data["id"])

    listed_runtimes = await list_runtimes(
        current_user=user,
        organization_id=None,
        project_id=None,
        db=db_session,
    )
    assert [runtime.id for runtime in listed_runtimes] == [runtime_id]

    # 3. Enable GitHub and Notion capabilities
    ri_github = await integration_service.enable_runtime_integration(
        runtime_id=runtime_id,
        data=RuntimeIntegrationCreate(
            integration_slug="github",
            connection_mode="end_user_oauth",
            enabled_capabilities=["repository_search", "file_retrieval", "issue_access"],
        ),
    )
    assert ri_github.integration_slug == "github"
    assert ri_github.connection_mode == "end_user_oauth"
    assert await integration_service.is_capability_enabled(runtime_id, "github", "file_retrieval") is True
    assert await integration_service.is_capability_enabled(runtime_id, "github", "write_actions") is False  # Not enabled

    # 4. Update capability permissions
    await integration_service.update_runtime_integration(
        runtime_id=runtime_id,
        integration_slug="github",
        data=RuntimeIntegrationUpdate(
            enabled_capabilities=["repository_search", "file_retrieval", "issue_access", "write_actions"]
        ),
    )
    assert await integration_service.is_capability_enabled(runtime_id, "github", "write_actions") is True

    # 5. List integrations on runtime
    items = await integration_service.list_runtime_integrations(runtime_id)
    assert len(items) == 1

    # 6. Generate API Keys across environments
    dev_key = await apikey_service.create_key(
        user_id=user.id,
        data=ApiKeyCreate(
            name="Staging Integration Key",
            runtime_id=runtime_id,
            environment="staging",
            scopes=["read", "write"],
        ),
    )
    assert dev_key["api_key"].runtime_id == runtime_id
    assert dev_key["api_key"].environment == "staging"
    assert dev_key["raw_key"].startswith("sk_test_")

    # 7. Disable integration
    await integration_service.disable_runtime_integration(runtime_id, "github")
    assert await integration_service.is_capability_enabled(runtime_id, "github", "file_retrieval") is False


@pytest.mark.asyncio
async def test_runtime_configuration_mutations_require_owner_access(db_session: AsyncSession) -> None:
    uow = UnitOfWork(db_session)
    owner = await uow.users.create(email="runtime_owner@zyntry.space", name="Owner")
    outsider = await uow.users.create(email="runtime_outsider@zyntry.space", name="Outsider")
    await uow.commit()
    runtime = await RuntimeService(uow).get_or_create(
        RuntimeCreate(name="Protected Runtime"),
        default_user_id=owner.id,
    )

    with pytest.raises(HTTPException) as update_error:
        await update_runtime(
            runtime_id=runtime["id"],
            body=RuntimeUpdate(name="Unauthorized Rename"),
            current_user=outsider,
            db=db_session,
        )
    assert update_error.value.status_code == 403

    with pytest.raises(HTTPException) as delete_error:
        await delete_runtime(
            runtime_id=runtime["id"],
            current_user=outsider,
            db=db_session,
        )
    assert delete_error.value.status_code == 403
