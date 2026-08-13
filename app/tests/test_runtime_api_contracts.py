from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api.v1.logs.router import list_logs
from app.services.runtime_assistant.planner import RuntimeAssistantPlanner
from app.services.runtime_assistant.schemas import RuntimeContext, UserRole
from app.services.runtime_assistant.service import _get_available_tools


@pytest.mark.asyncio
async def test_logs_router_maps_model_to_public_schema() -> None:
    project_id = uuid.uuid4()
    user = SimpleNamespace(organization_id=uuid.uuid4())
    project = SimpleNamespace(organization_id=user.organization_id)
    log = SimpleNamespace(
        id=uuid.uuid4(), project_id=project_id, method="POST", endpoint="/invoke",
        status=200, latency_ms=125, tokens=None, model="gpt-4o-mini",
        created_at=SimpleNamespace(isoformat=lambda: "2026-08-13T00:00:00+00:00"),
    )
    db = SimpleNamespace(
        get=AsyncMock(return_value=project),
        execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [log]))),
    )
    result = await list_logs(str(project_id), 50, 0, user, db)
    assert result[0].path == "/invoke"
    assert result[0].status_code == 200
    assert result[0].tokens_used == 0


def test_runtime_assistant_tools_remain_typed_for_planner() -> None:
    tools = _get_available_tools(UserRole.DEVELOPER)
    assert tools
    context = RuntimeContext(
        runtime_id=str(uuid.uuid4()), project_id=str(uuid.uuid4()),
        organization_id=str(uuid.uuid4()), user_id=str(uuid.uuid4()),
        user_role=UserRole.DEVELOPER,
    )
    planner = RuntimeAssistantPlanner(context=context, available_tools=tools)
    assert planner.tool_map
