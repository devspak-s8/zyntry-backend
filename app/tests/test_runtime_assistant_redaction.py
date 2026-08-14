from app.services.runtime_assistant.redaction import redact_sensitive
from types import SimpleNamespace
from unittest.mock import AsyncMock
import uuid
import pytest

from app.services.runtime_assistant.memory import RuntimeAssistantMemory
from datetime import datetime, timezone


def test_redacts_nested_credentials_and_bearer_tokens() -> None:
    result = redact_sensitive(
        {
            "access_token": "oauth-value",
            "nested": {
                "client_secret": "secret-value",
                "message": "Authorization: Bearer abc.def.ghi",
            },
            "items": [{"api-key": "key-value"}],
        }
    )

    assert result["access_token"] == "[REDACTED]"
    assert result["nested"]["client_secret"] == "[REDACTED]"
    assert "abc.def.ghi" not in result["nested"]["message"]
    assert result["items"][0]["api-key"] == "[REDACTED]"


def test_redaction_normalizes_json_unsafe_runtime_values() -> None:
    now = datetime.now(timezone.utc)
    result = redact_sensitive({"observed_at": now, "id": uuid.uuid4()})
    assert result["observed_at"] == now.isoformat()
    assert isinstance(result["id"], str)


@pytest.mark.asyncio
async def test_chat_memory_redacts_credentials_before_persistence() -> None:
    project_id = uuid.uuid4()
    uow = SimpleNamespace(
        runtimes=SimpleNamespace(
            get=AsyncMock(return_value=SimpleNamespace(project_id=project_id))
        ),
        memory_records=SimpleNamespace(create=AsyncMock()),
        commit=AsyncMock(),
    )

    await RuntimeAssistantMemory(uow, str(uuid.uuid4())).save_chat_message(
        "user", "Authorization: Bearer very.secret.token"
    )

    stored = uow.memory_records.create.await_args.kwargs["content"]
    assert "very.secret.token" not in stored
