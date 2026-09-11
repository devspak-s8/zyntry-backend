"""Opt-in contract tests for infrastructure dependencies.

These tests intentionally do not fall back to the unit-test SQLite database or
mocked provider adapters. Set ``RUN_INTEGRATION_TESTS=1`` and provide the
specific service URL/credentials when running them in a private test
environment.
"""

from __future__ import annotations

import os
import uuid

import pytest

pytestmark = pytest.mark.integration


def _integration_enabled() -> bool:
    return os.getenv("RUN_INTEGRATION_TESTS", "").lower() in {"1", "true", "yes"}


def _require(name: str) -> str:
    if not _integration_enabled():
        pytest.skip("set RUN_INTEGRATION_TESTS=1 to run integration contracts")
    value = os.getenv(name)
    if not value:
        pytest.skip(f"{name} is not configured")
    return value


@pytest.mark.asyncio
async def test_postgres_contract() -> None:
    url = _require("TEST_POSTGRES_URL")
    asyncpg = pytest.importorskip("asyncpg")
    connection = await asyncpg.connect(url, timeout=10)
    try:
        assert await connection.fetchval("SELECT 1") == 1
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_redis_contract() -> None:
    url = _require("TEST_REDIS_URL")
    redis = pytest.importorskip("redis.asyncio")
    client = redis.from_url(url, decode_responses=True, socket_timeout=10)
    key = f"zyntry:contract:{uuid.uuid4().hex}"
    try:
        assert await client.ping()
        assert await client.set(key, "ok", ex=30)
        assert await client.get(key) == "ok"
    finally:
        await client.delete(key)
        await client.aclose()


@pytest.mark.asyncio
async def test_provider_contract() -> None:
    provider_name = _require("TEST_PROVIDER").lower()
    api_key = _require("TEST_PROVIDER_API_KEY")
    model = _require("TEST_PROVIDER_MODEL")

    from app.services.model_providers import PROVIDER_REGISTRY

    provider_cls = PROVIDER_REGISTRY.get(provider_name)
    if provider_cls is None:
        pytest.fail(f"provider {provider_name!r} is not registered")
    provider = provider_cls()
    assert await provider.test_connection(api_key), "provider health check failed"
    response = await provider.chat_completion(
        api_key=api_key,
        model=model,
        messages=[{"role": "user", "content": "Reply with the word contract."}],
        max_tokens=8,
        temperature=0,
    )
    assert str(response).strip()

