from __future__ import annotations

import json
import uuid
from typing import Any

import redis.asyncio as aioredis

from app.core.config import settings


class RuntimeCache:
    def __init__(self) -> None:
        self._url = settings.redis_url
        self._client: aioredis.Redis | None = None

    @property
    def client(self) -> aioredis.Redis:
        if self._client is None:
            self._client = aioredis.from_url(self._url, decode_responses=True)
        return self._client

    def _key(self, runtime_id: str) -> str:
        return f"runtime:{runtime_id}"

    async def get(self, runtime_id: str) -> dict[str, Any] | None:
        raw = await self.client.get(self._key(runtime_id))
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    async def set(self, runtime_id: str, data: dict[str, Any], ttl: int = 300) -> None:
        await self.client.set(self._key(runtime_id), json.dumps(data), ex=ttl)

    async def delete(self, runtime_id: str) -> None:
        await self.client.delete(self._key(runtime_id))

    async def invalidate_project(self, project_id: str) -> None:
        pattern = f"runtime:project:{project_id}:*"
        keys = []
        async for key in self.client.scan_iter(match=pattern):
            keys.append(key)
        if keys:
            await self.client.delete(*keys)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()


runtime_cache = RuntimeCache()
