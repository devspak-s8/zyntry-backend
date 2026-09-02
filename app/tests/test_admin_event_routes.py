from __future__ import annotations

import pytest

from app.admin.auth import AdminAuth
from app.admin.constants import AdminRole
from app.admin.models import AdminEventTimeline, AdminUser
from app.core.config import settings
from app.core.security import hash_password
from app.models.users import User


@pytest.mark.asyncio
async def test_admin_event_and_user_routes_return_timestamps(
    client, db_session, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "JWT_SECRET", "test-admin-jwt-secret-at-least-32-bytes")
    password = "strong-admin-test-password"
    user = User(
        email="route-admin@example.com",
        name="Route Admin",
        hashed_password=hash_password(password),
        is_active=True,
        is_superuser=True,
        email_verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        AdminUser(
            user_id=user.id,
            role=AdminRole.SUPER_ADMIN,
            is_active=True,
        )
    )
    await db_session.commit()

    login = await AdminAuth(db_session).login(
        user.email, password, "127.0.0.1", "pytest"
    )
    client.headers["Authorization"] = f"Bearer {login['access_token']}"

    event = AdminEventTimeline(
        request_id="request-1",
        event_type="invocation.completed",
        title="Invocation completed",
        sequence=1,
        status_code=200,
        latency_ms=42,
        data={"country": "Nigeria"},
    )
    db_session.add(event)
    await db_session.commit()

    events_response = await client.get("/api/v1/admin/events?limit=20&offset=0")
    live_response = await client.get("/api/v1/admin/events/requests/live?limit=20")
    users_response = await client.get("/api/v1/admin/users?limit=50&offset=0")

    assert events_response.status_code == 200
    assert events_response.json()[0]["timestamp"]
    assert live_response.status_code == 200
    assert live_response.json()[0]["timestamp"]
    assert users_response.status_code == 200
    assert users_response.json()[0]["created_at"]
