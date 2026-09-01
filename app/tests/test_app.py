import pytest


@pytest.mark.asyncio
async def test_health_route(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.headers["cross-origin-resource-policy"] == "same-site"
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_admin_security_scan_requires_super_admin(client):
    response = await client.post("/api/v1/admin/security/scan")
    assert response.status_code == 401
