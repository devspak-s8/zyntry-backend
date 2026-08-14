from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.actions.providers import slack as slack_module
from app.services.actions.providers.slack import SlackActionProvider


@pytest.mark.asyncio
async def test_slack_read_channels_executes_connected_api(monkeypatch) -> None:
    response = SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {"ok": True, "channels": [{"id": "C1", "name": "general"}]},
    )
    client = SimpleNamespace(post=AsyncMock(return_value=response))
    monkeypatch.setattr(slack_module, "get_http_client", AsyncMock(return_value=client))

    result = await SlackActionProvider({"token": "xoxb-secret"}).execute(
        "read_channels", {}, {}
    )

    assert result.success is True
    _, kwargs = client.post.await_args
    assert kwargs["headers"]["Authorization"] == "Bearer xoxb-secret"
    assert kwargs["json"]["limit"] == 100


@pytest.mark.asyncio
async def test_slack_api_error_is_not_reported_as_success(monkeypatch) -> None:
    response = SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {"ok": False, "error": "missing_scope"},
    )
    client = SimpleNamespace(post=AsyncMock(return_value=response))
    monkeypatch.setattr(slack_module, "get_http_client", AsyncMock(return_value=client))

    result = await SlackActionProvider({"token": "xoxb-secret"}).execute(
        "search_messages", {"query": "incident"}, {}
    )

    assert result.success is False
    assert result.error == "Slack API error: missing_scope"
