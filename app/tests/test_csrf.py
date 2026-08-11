from __future__ import annotations

import pytest
from httpx import AsyncClient


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
