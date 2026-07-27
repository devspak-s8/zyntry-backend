from __future__ import annotations

import json
from typing import Any

import redis.asyncio as aioredis

from app.core.config import settings


class Cache:
    def __init__(self, url: str | None = None) -> None:
        self._url = url or settings.redis_url
        self._client: aioredis.Redis | None = None

    @property
    def client(self) -> aioredis.Redis:
        if self._client is None:
            self._client = aioredis.from_url(self._url, decode_responses=True)
        return self._client

    async def get(self, key: str) -> Any | None:
        value = await self.client.get(key)
        return json.loads(value) if value is not None else None

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        await self.client.set(key, json.dumps(value), ex=ttl)

    async def delete(self, key: str) -> None:
        await self.client.delete(key)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()


cache = Cache()
