from __future__ import annotations

from types import SimpleNamespace
import sys
from unittest.mock import AsyncMock, patch

import pytest

from app.services.actions.planner import ActionPlanner


@pytest.mark.asyncio
async def test_action_planner_awaits_openai_and_parses_json() -> None:
    completion = AsyncMock(
        return_value=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content='{"use_tools": false, "actions": [], "reasoning": "No action needed"}'
                    )
                )
            ]
        )
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=completion))
    )

    openai_module = SimpleNamespace(AsyncOpenAI=lambda: client)
    with patch.dict(sys.modules, {"openai": openai_module}):
        result = await ActionPlanner.plan("Hello", [])

    assert result == {
        "use_tools": False,
        "actions": [],
        "reasoning": "No action needed",
    }
    completion.assert_awaited_once()


@pytest.mark.asyncio
async def test_action_planner_fails_closed_when_provider_errors() -> None:
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=AsyncMock(side_effect=RuntimeError("unavailable")))
        )
    )

    openai_module = SimpleNamespace(AsyncOpenAI=lambda: client)
    with patch.dict(sys.modules, {"openai": openai_module}):
        result = await ActionPlanner.plan("Do something", [])

    assert result == {
        "use_tools": False,
        "actions": [],
        "reasoning": "Planning failed",
    }
