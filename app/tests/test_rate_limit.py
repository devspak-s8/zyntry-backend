from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.middleware.rate_limit import RedisRateLimiter


@pytest.mark.asyncio
async def test_redis_rate_limiter_fails_closed_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    limiter = RedisRateLimiter("redis://unused")
    monkeypatch.setattr(limiter, "_get_client", AsyncMock(side_effect=RuntimeError("offline")))

    allowed, remaining, _ = await limiter.is_allowed("key", limit=10, window=60)

    assert allowed is False
    assert remaining == 0


@pytest.mark.asyncio
async def test_redis_rate_limiter_can_explicitly_fail_open(monkeypatch: pytest.MonkeyPatch) -> None:
    limiter = RedisRateLimiter("redis://unused", fail_open=True)
    monkeypatch.setattr(limiter, "_get_client", AsyncMock(side_effect=RuntimeError("offline")))

    allowed, remaining, _ = await limiter.is_allowed("key", limit=10, window=60)

    assert allowed is True
    assert remaining == 9

