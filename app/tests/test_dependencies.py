from __future__ import annotations

import json
import uuid

import pytest

from app.api.v1 import dependencies


class _CachedRedis:
    def __init__(self, value: dict[str, object]) -> None:
        self.value = value

    async def get(self, _key: str) -> str:
        return json.dumps(self.value)


@pytest.mark.asyncio
async def test_cached_session_restores_uuid_types(monkeypatch: pytest.MonkeyPatch) -> None:
    user_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    monkeypatch.setattr(
        dependencies,
        "redis_client",
        _CachedRedis(
            {
                "id": str(user_id),
                "organization_id": str(organization_id),
                "email": "cached@example.com",
                "name": "Cached User",
                "is_active": True,
                "is_superuser": False,
                "email_verified": True,
            }
        ),
    )

    user = await dependencies._get_session_user("session-token", db=None)  # type: ignore[arg-type]

    assert user is not None
    assert user.id == user_id
    assert isinstance(user.id, uuid.UUID)
    assert user.organization_id == organization_id
    assert isinstance(user.organization_id, uuid.UUID)
    assert user.name == "Cached User"
    assert user.email_verified is True
