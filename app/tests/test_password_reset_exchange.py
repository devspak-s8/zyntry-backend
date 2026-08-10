from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.v1.auth.router import reset_password, verify_reset_code
from app.core.security import now


@pytest.mark.asyncio
async def test_verification_code_is_exchanged_for_short_lived_token() -> None:
    user = SimpleNamespace(id=uuid4(), email="user@example.com")
    code_obj = SimpleNamespace(used=False, expires_at=now() + timedelta(minutes=5))
    result = SimpleNamespace(scalar_one_or_none=lambda: code_obj)
    db = SimpleNamespace(
        execute=AsyncMock(return_value=result),
        add=lambda value: setattr(db, "added", value),
        commit=AsyncMock(),
    )

    with (
        patch(
            "app.api.v1.auth.router._get_user_by_email",
            new=AsyncMock(return_value=user),
        ),
        patch(
            "app.api.v1.auth.router.generate_session_token",
            return_value="A" * 48,
        ),
    ):
        response = await verify_reset_code("user@example.com", "ab12cd", db)

    assert response == {"reset_token": f"rst_{'A' * 48}"}
    assert code_obj.used is True
    assert db.added.user_id == user.id
    assert db.added.expires_at <= now() + timedelta(minutes=10, seconds=1)
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_used_verification_code_cannot_be_replayed() -> None:
    user = SimpleNamespace(id=uuid4())
    code_obj = SimpleNamespace(used=True, expires_at=now() + timedelta(minutes=5))
    db = SimpleNamespace(
        execute=AsyncMock(
            return_value=SimpleNamespace(scalar_one_or_none=lambda: code_obj)
        )
    )

    with patch(
        "app.api.v1.auth.router._get_user_by_email",
        new=AsyncMock(return_value=user),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await verify_reset_code("user@example.com", "AB12CD", db)

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_raw_six_character_code_cannot_reset_password() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await reset_password("AB12CD", "new-password", AsyncMock())

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid or expired reset token"
