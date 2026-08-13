from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.runtime_assistant.memory import RuntimeAssistantMemory
from app.services.runtime_assistant.schemas import UserRole
from app.services.runtime_assistant.service import _parse_user_role


@pytest.mark.asyncio
async def test_chat_memory_uses_project_scope_and_text_content() -> None:
    project_id = uuid.uuid4()
    runtime_id = uuid.uuid4()
    uow = SimpleNamespace(
        runtimes=SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(project_id=project_id))),
        memory_records=SimpleNamespace(create=AsyncMock()),
        commit=AsyncMock(),
    )

    await RuntimeAssistantMemory(uow, str(runtime_id)).save_chat_message("user", "What failed?")

    kwargs = uow.memory_records.create.await_args.kwargs
    assert kwargs["project_id"] == project_id
    assert kwargs["content"] == "What failed?"
    assert kwargs["value"]["runtime_id"] == str(runtime_id)
    assert "runtime_id" not in {key for key in kwargs if key != "value"}


def test_runtime_assistant_accepts_role_values() -> None:
    assert _parse_user_role("developer") is UserRole.DEVELOPER
    assert _parse_user_role("owner") is UserRole.OWNER
    assert _parse_user_role("unknown") is UserRole.VIEWER


@pytest.mark.asyncio
async def test_action_memory_serializes_datetime_results() -> None:
    project_id = uuid.uuid4()
    runtime_id = uuid.uuid4()
    uow = SimpleNamespace(
        runtimes=SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(project_id=project_id))),
        memory_records=SimpleNamespace(create=AsyncMock()),
        commit=AsyncMock(),
    )
    timestamp = datetime.now(timezone.utc)
    await RuntimeAssistantMemory(uow, str(runtime_id)).save_action(
        "get_runtime_summary", {"last_build": timestamp}
    )
    stored = uow.memory_records.create.await_args.kwargs["value"]["result"]
    assert stored["last_build"] == timestamp.isoformat()
