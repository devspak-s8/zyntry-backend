from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.api.v1.auth.router import forgot_password


@pytest.mark.asyncio
async def test_unverified_account_can_request_password_reset() -> None:
    user = SimpleNamespace(
        id=uuid4(),
        email="unverified@example.com",
        name="Unverified User",
        email_verified=False,
    )
    db = SimpleNamespace(
        add=lambda value: setattr(db, "added", value),
        commit=AsyncMock(),
    )

    with (
        patch(
            "app.api.v1.auth.router._get_user_by_email",
            new=AsyncMock(return_value=user),
        ),
        patch(
            "app.api.v1.auth.router.generate_verification_token",
            return_value="AB12CD",
        ),
        patch("app.services.notifications.enqueue_notification") as enqueue,
    ):
        response = await forgot_password("unverified@example.com", db)

    assert response == {
        "message": "If an account exists with that email, a reset link has been sent."
    }
    assert db.added.user_id == user.id
    db.commit.assert_awaited_once()
    enqueue.assert_called_once()
    event = enqueue.call_args.args[0]
    assert event.recipient == user.email
    assert event.data["token"] == "AB12CD"
    assert user.email_verified is False
