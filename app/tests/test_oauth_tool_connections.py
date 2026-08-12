from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.services.oauth.service import OAuthError, OAuthService
from app.services.integrations import IntegrationService
from app.services.tools import ToolService


@pytest.mark.asyncio
async def test_oauth_provider_lookup_uses_database_without_recursing() -> None:
    provider = SimpleNamespace(name="github", is_enabled=True)
    scalar_result = SimpleNamespace(first=lambda: provider)
    session = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: scalar_result))
    )
    service = OAuthService(SimpleNamespace(session=session))
    service._provider_cache.clear()

    result = await service.get_provider("github")

    assert result is provider
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_missing_oauth_provider_reports_environment_configuration() -> None:
    scalar_result = SimpleNamespace(first=lambda: None)
    session = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: scalar_result))
    )
    service = OAuthService(SimpleNamespace(session=session))
    service._provider_cache.clear()

    with pytest.raises(OAuthError, match="not configured on this environment"):
        await service.authorize("github", uuid4(), uuid4())


@pytest.mark.asyncio
async def test_oauth_completion_creates_connected_project_tool() -> None:
    project_id = str(uuid4())

    async def create_tool(**kwargs):
        return SimpleNamespace(
            id=uuid4(),
            project_id=kwargs["project_id"],
            name=kwargs["name"],
            schema=kwargs["schema"],
            created_at=datetime.now(UTC),
        )

    tools = SimpleNamespace(
        get_by_project=AsyncMock(return_value=[]),
        create=AsyncMock(side_effect=create_tool),
        update=AsyncMock(),
    )
    uow = SimpleNamespace(tools=tools, commit=AsyncMock())

    result = await ToolService(uow).connect_oauth_catalog_tool(
        connector_key="github",
        project_id=project_id,
        display_name="Octocat",
        oauth_connection_id="oauth-1",
    )

    assert result["connected"] is True
    assert result["status"] == "connected"
    schema = tools.create.await_args.kwargs["schema"]
    assert schema["_zyntry_connection"]["oauth_connection_id"] == "oauth-1"
    uow.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_both_purpose_reuses_one_oauth_connection_for_tool_and_source() -> None:
    project_id = str(uuid4())

    async def create_tool(**kwargs):
        return SimpleNamespace(
            id=uuid4(),
            project_id=kwargs["project_id"],
            name=kwargs["name"],
            schema=kwargs["schema"],
        )

    async def create_source(**kwargs):
        return SimpleNamespace(id=uuid4(), **kwargs)

    uow = SimpleNamespace(
        tools=SimpleNamespace(
            get_by_project=AsyncMock(return_value=[]),
            create=AsyncMock(side_effect=create_tool),
            update=AsyncMock(),
        ),
        knowledge_sources=SimpleNamespace(
            get_by_project=AsyncMock(return_value=[]),
            create=AsyncMock(side_effect=create_source),
            update=AsyncMock(),
        ),
        commit=AsyncMock(),
    )

    result = await IntegrationService(uow).materialize_oauth_connection(
        provider="github",
        project_id=project_id,
        oauth_connection_id="oauth-shared",
        display_name="Engineering GitHub",
        purpose="both",
        source_config={"repository": "zyntry/backend"},
    )

    assert result["tool_id"]
    assert result["source_id"]
    tool_schema = uow.tools.create.await_args.kwargs["schema"]
    source_config = uow.knowledge_sources.create.await_args.kwargs["config"]
    assert tool_schema["_zyntry_connection"]["oauth_connection_id"] == "oauth-shared"
    assert source_config["oauth_connection_id"] == "oauth-shared"
    assert source_config["repository"] == "zyntry/backend"
