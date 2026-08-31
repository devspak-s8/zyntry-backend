import pytest


@pytest.mark.asyncio
async def test_health_route(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.headers["cross-origin-resource-policy"] == "same-site"
    assert response.headers["cache-control"] == "no-store"
