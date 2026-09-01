from __future__ import annotations

import pytest
from httpx import AsyncClient
from starlette.requests import Request

from app.core.config import settings
from app.middleware.csrf import CSRFMiddleware


@pytest.mark.asyncio
async def test_csrf_token_endpoint_sets_cookie_and_returns_matching_token(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/v1/auth/csrf-token")

    assert response.status_code == 200
    token = response.json()["csrf_token"]
    assert token
    assert response.cookies["zyntra_csrf"] == token
    assert "HttpOnly" in response.headers["set-cookie"]
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_csrf_token_endpoint_reuses_existing_token(client: AsyncClient) -> None:
    client.cookies.set("zyntra_csrf", "existing-token")

    response = await client.get("/api/v1/auth/csrf-token")

    assert response.status_code == 200
    assert response.json() == {"csrf_token": "existing-token"}


@pytest.mark.asyncio
async def test_multipart_mutations_still_require_csrf(monkeypatch) -> None:
    monkeypatch.setattr(settings, "APP_DEBUG", False)
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/api/v1/knowledge/documents/upload",
        "raw_path": b"/api/v1/knowledge/documents/upload",
        "query_string": b"",
        "headers": [
            (b"content-type", b"multipart/form-data; boundary=test"),
            (b"cookie", b"zyntra_session=session; zyntra_csrf=token"),
        ],
        "client": ("127.0.0.1", 1234),
        "server": ("test", 443),
    }
    request = Request(scope)
    called = False

    async def call_next(_request):
        nonlocal called
        called = True

    middleware = CSRFMiddleware(app=lambda scope, receive, send: None)
    response = await middleware.dispatch(request, call_next)

    assert response.status_code == 403
    assert called is False


@pytest.mark.asyncio
async def test_admin_login_is_not_blocked_by_stale_session_cookie(monkeypatch) -> None:
    monkeypatch.setattr(settings, "APP_DEBUG", False)
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/api/v1/admin/auth/login",
        "raw_path": b"/api/v1/admin/auth/login",
        "query_string": b"",
        "headers": [(b"cookie", b"zyntra_refresh=expired")],
        "client": ("127.0.0.1", 1234),
        "server": ("test", 443),
    }
    request = Request(scope)
    called = False

    async def call_next(_request):
        nonlocal called
        called = True
        return None

    middleware = CSRFMiddleware(app=lambda scope, receive, send: None)
    response = await middleware.dispatch(request, call_next)

    assert response is None
    assert called is True
