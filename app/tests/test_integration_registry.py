from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.main import app as fastapi_app
from app.models.users import User
from app.repositories import UnitOfWork
from app.schemas.integrations import RuntimeIntegrationCreate
from app.services.integrations.definitions import integration_registry
from app.services.integrations.service import IntegrationService


@pytest.mark.asyncio
async def test_integration_registry_unit_definitions() -> None:
    # 1. Verify developer integrations exist
    github = integration_registry.get("github")
    assert github is not None
    assert github.category == "developer"
    assert github.status == "available"
    assert github.supports_zyntry_managed is True
    assert github.supports_end_user_oauth is True
    assert any(c.slug == "repository_search" for c in github.capabilities)

    gitlab = integration_registry.get("gitlab")
    assert gitlab is not None
    assert gitlab.status == "beta"

    bitbucket = integration_registry.get("bitbucket")
    assert bitbucket is not None
    assert bitbucket.status == "coming_soon"

    # 2. Verify database integrations and aliases
    postgres = integration_registry.get("postgres")
    postgresql = integration_registry.get("postgresql")
    assert postgres is not None
    assert postgresql is not None
    assert postgres.slug == postgresql.slug
    assert postgres.category == "databases"
    assert postgres.supports_database_credentials is True
    assert any(c.slug == "query" for c in postgres.capabilities)

    # 3. Verify communication integrations
    slack = integration_registry.get("slack")
    assert slack is not None
    assert slack.category == "communication"
    assert any(c.slug == "message_search" for c in slack.capabilities)

    # 4. Verify AI provider integrations
    openai = integration_registry.get("openai")
    assert openai is not None
    assert openai.category == "ai_providers"
    assert openai.supports_api_key is True


@pytest.mark.asyncio
async def test_integration_registry_filtering() -> None:
    # Category filter
    dev_integrations = integration_registry.list_all(category="developer")
    assert len(dev_integrations) >= 3
    assert all(i.category == "developer" for i in dev_integrations)

    db_integrations = integration_registry.list_all(category="databases")
    assert len(db_integrations) >= 5
    assert all(i.category == "databases" for i in db_integrations)

    # Status filter
    available_only = integration_registry.list_all(status="available")
    assert all(i.status == "available" for i in available_only)
    assert any(i.slug == "github" for i in available_only)

    coming_soon_only = integration_registry.list_all(status="coming_soon")
    assert all(i.status == "coming_soon" for i in coming_soon_only)
    assert any(i.slug == "bitbucket" for i in coming_soon_only)

    # Search filter
    search_results = integration_registry.list_all(search="postgres")
    assert any(i.slug == "postgresql" for i in search_results)


@pytest.mark.asyncio
async def test_integration_registry_api_catalog(client: AsyncClient, db_session: AsyncSession) -> None:
    uow = UnitOfWork(db_session)
    user = await uow.users.create(email="integ_api_user@zyntry.space", name="Registry Tester", is_active=True)
    await uow.commit()

    fastapi_app.dependency_overrides[get_current_user] = lambda: user

    try:
        # 1. Fetch entire catalog
        res = await client.get("/api/v1/integrations")
        assert res.status_code == 200
        data = res.json()
        assert "integrations" in data
        assert "total" in data
        assert data["total"] >= 25
        slugs = {item["slug"] for item in data["integrations"]}
        assert "github" in slugs
        assert "slack" in slugs
        assert "postgresql" in slugs
        assert "document_storage" in slugs
        assert "openai" in slugs

        # 2. Filter by category
        res_dev = await client.get("/api/v1/integrations?category=developer")
        assert res_dev.status_code == 200
        dev_data = res_dev.json()
        assert all(item["category"] == "developer" for item in dev_data["integrations"])

        # 3. Filter by status
        res_avail = await client.get("/api/v1/integrations?status=available")
        assert res_avail.status_code == 200
        avail_data = res_avail.json()
        assert all(item["status"] == "available" for item in avail_data["integrations"])

        # 4. Fetch single integration definition
        res_single = await client.get("/api/v1/integrations/github")
        assert res_single.status_code == 200
        github_data = res_single.json()
        assert github_data["slug"] == "github"
        assert github_data["name"] == "GitHub"
        assert "repository_search" in [c["slug"] for c in github_data["capabilities"]]
        assert github_data["supports_zyntry_managed"] is True
        assert github_data["supports_end_user_oauth"] is True

        # 5. Invalid integration returns 404
        res_404 = await client.get("/api/v1/integrations/unknown_nonexistent_tool")
        assert res_404.status_code == 404
    finally:
        fastapi_app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_integration_service_validation_and_enablement(db_session: AsyncSession) -> None:
    uow = UnitOfWork(db_session)
    service = IntegrationService(uow)

    user = await uow.users.create(email="integration_test@zyntry.space", name="Integ Tester", is_active=True)
    runtime = await uow.runtimes.create(user_id=user.id, name="Test Integration Runtime")
    await uow.commit()

    # 1. Successfully enable available integration (GitHub)
    ri = await service.enable_runtime_integration(
        runtime_id=runtime.id,
        data=RuntimeIntegrationCreate(
            integration_slug="github",
            connection_mode="zyntry_managed",
            enabled_capabilities=["repository_search", "file_retrieval"],
        ),
        user_id=user.id,
    )
    assert ri.integration_slug == "github"
    assert ri.connection_mode == "zyntry_managed"
    assert ri.enabled_capabilities == ["repository_search", "file_retrieval"]

    # Capability check
    assert await service.is_capability_enabled(runtime.id, "github", "repository_search") is True
    assert await service.is_capability_enabled(runtime.id, "github", "send_messages") is False

    # 2. Reject unsupported integration
    with pytest.raises(ValueError, match="not supported"):
        await service.enable_runtime_integration(
            runtime_id=runtime.id,
            data=RuntimeIntegrationCreate(integration_slug="unsupported_service_xyz"),
            user_id=user.id,
        )

    # 3. Reject coming_soon integration for active runtime
    with pytest.raises(ValueError, match="coming_soon"):
        await service.enable_runtime_integration(
            runtime_id=runtime.id,
            data=RuntimeIntegrationCreate(integration_slug="bitbucket"),
            user_id=user.id,
        )

    # 4. Reject unsupported connection mode
    with pytest.raises(ValueError, match="Connection mode"):
        await service.enable_runtime_integration(
            runtime_id=runtime.id,
            data=RuntimeIntegrationCreate(
                integration_slug="postgresql",
                connection_mode="end_user_oauth",  # PostgreSQL does not support end-user OAuth
            ),
            user_id=user.id,
        )

    # 5. Reject invalid/unsupported capability
    with pytest.raises(ValueError, match="Invalid capabilities"):
        await service.enable_runtime_integration(
            runtime_id=runtime.id,
            data=RuntimeIntegrationCreate(
                integration_slug="github",
                enabled_capabilities=["fake_unsupported_action"],
            ),
            user_id=user.id,
        )

    # 6. Reject unauthorized user
    other_user = await uow.users.create(email="other_attacker@zyntry.space", name="Other", is_active=True)
    await uow.commit()
    with pytest.raises(PermissionError, match="Unauthorized"):
        await service.enable_runtime_integration(
            runtime_id=runtime.id,
            data=RuntimeIntegrationCreate(integration_slug="github"),
            user_id=other_user.id,
        )
