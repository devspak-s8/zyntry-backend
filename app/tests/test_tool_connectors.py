from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from app.services.tools import TOOL_CATALOG, ToolService


def _tool(*, schema: dict | None = None) -> SimpleNamespace:
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=uuid4(),
        name="GitHub",
        description="GitHub connector",
        schema=schema or {},
        implementation="connector://github",
        project_id=uuid4(),
        created_at=now,
    )


def test_catalog_exposes_only_real_registered_connectors() -> None:
    catalog = ToolService.catalog()

    assert catalog
    assert {item["key"] for item in catalog}.issubset(
        {item["key"] for item in TOOL_CATALOG}
    )
    assert "github" in {item["key"] for item in catalog}


def test_tool_list_never_exposes_encrypted_credentials() -> None:
    schema = {
        "type": "connector",
        "_zyntry_connection": {
            "connector": "github",
            "status": "connected",
            "credentials_encrypted": "secret-ciphertext",
            "config": {"private": "value"},
        },
    }

    public = ToolService._public_schema(schema)

    assert "credentials_encrypted" not in public["_zyntry_connection"]
    assert "config" not in public["_zyntry_connection"]
    assert public["_zyntry_connection"]["status"] == "connected"


@pytest.mark.asyncio
async def test_connect_catalog_tool_tests_and_persists_status(monkeypatch) -> None:
    project_id = str(uuid4())
    async def create_tool(**kwargs):
        created = _tool(schema=kwargs["schema"])
        created.project_id = kwargs["project_id"]
        created.name = kwargs["name"]
        return created

    tools = SimpleNamespace(
        get_by_project=AsyncMock(return_value=[]),
        create=AsyncMock(side_effect=create_tool),
        update=AsyncMock(),
    )
    uow = SimpleNamespace(tools=tools, commit=AsyncMock())
    connector = SimpleNamespace(
        test=AsyncMock(return_value={"success": True, "message": "Connected as tester"})
    )
    monkeypatch.setattr("app.services.tools.registry.create", Mock(return_value=connector))
    monkeypatch.setattr("app.services.tools.encrypt_value", Mock(return_value="encrypted"))

    result = await ToolService(uow).connect_catalog_tool(
        connector_key="postgres",
        project_id=project_id,
        display_name="Engineering GitHub",
        config={},
        credentials={"connection_string": "do-not-return"},
    )

    assert result["connected"] is True
    assert result["status"] == "connected"
    assert result["message"] == "Connected as tester"
    stored_schema = tools.create.await_args.kwargs["schema"]
    assert stored_schema["_zyntry_connection"]["credentials_encrypted"] == "encrypted"
    assert "do-not-return" not in str(result)
    uow.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_unconnected_catalog_tool_has_explicit_status() -> None:
    project_id = str(uuid4())
    uow = SimpleNamespace(
        tools=SimpleNamespace(get_by_project=AsyncMock(return_value=[])),
    )

    result = await ToolService(uow).get_catalog_tool_status("github", project_id)

    assert result == {
        "connector": "github",
        "project_id": project_id,
        "connected": False,
        "status": "not_connected",
        "message": None,
        "tool_id": None,
        "display_name": None,
        "tested_at": None,
    }
