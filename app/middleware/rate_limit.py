from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from typing import Callable

from fastapi import Request, Response
from fastapi.security import HTTPAuthorizationCredentials
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("app.middleware.rate_limit")


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._store: dict[str, list[float]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def is_allowed(self, key: str, limit: int, window: int) -> tuple[bool, int, int]:
        now_ts = time.time()
        async with self._lock:
            timestamps = self._store[key]
            cutoff = now_ts - window
            self._store[key] = [t for t in timestamps if t > cutoff]
            remaining = max(0, limit - len(self._store[key]))
            if len(self._store[key]) >= limit:
                reset = self._store[key][0] + window if self._store[key] else now_ts + window
                return False, 0, int(reset)
            self._store[key].append(now_ts)
            return True, remaining - 1, int(now_ts + window)


class RedisRateLimiter:
    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._client = None

    async def _get_client(self):
        if self._client is None:
            import redis.asyncio as aioredis

            self._client = aioredis.from_url(
                self._redis_url,
                decode_responses=True,
                socket_connect_timeout=1,
                socket_timeout=1,
            )
        return self._client

    async def is_allowed(self, key: str, limit: int, window: int) -> tuple[bool, int, int]:
        try:
            client = await self._get_client()
            now_ts = time.time()
            member = f"{now_ts}:{id(self)}"
            pipeline = client.pipeline()
            pipeline.zadd(key, {member: now_ts})
            pipeline.zremrangebyscore(key, 0, now_ts - window)
            pipeline.zcard(key)
            pipeline.expire(key, window + 1)
            results = await pipeline.execute()
            count = results[2]
            remaining = max(0, limit - count)
            if count >= limit:
                reset = int(now_ts + window)
                return False, 0, reset
            return True, remaining - 1, int(now_ts + window)
        except Exception:
            return True, limit - 1, int(time.time() + window)


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: Callable, limit: int = 60, window: int = 60) -> None:
        super().__init__(app)
        self.limit = limit
        self.window = window
        if settings.REDIS_HOST and settings.REDIS_PORT:
            self._limiter = RedisRateLimiter(settings.redis_url)
        else:
            self._limiter = InMemoryRateLimiter()

    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/health" or not request.url.path.startswith("/api"):
            return await call_next(request)

        if request.headers.get("content-type", "").startswith("multipart/form-data"):
            return await call_next(request)

        user_id = ""
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            user_id = auth_header[7:]
        elif request.cookies.get("zyntra_session"):
            user_id = f"session:{request.cookies['zyntra_session'][:16]}"

        client_ip = request.client.host if request.client else "unknown"
        base_key = f"{client_ip}:{request.url.path}"
        key = f"user:{user_id}:{base_key}" if user_id else f"ip:{base_key}"

        allowed, remaining, reset = await self._limiter.is_allowed(key, self.limit, self.window)

        response = Response() if not allowed else None
        if response is None:
            response = await call_next(request)

        response.headers["X-RateLimit-Limit"] = str(self.limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(reset)

        if not allowed:
            logger.warning("rate limit exceeded", extra={"path": request.url.path, "ip": client_ip, "user_id": user_id})
            response.status_code = 429
            response.headers["Retry-After"] = str(self.window)
            response.body = b'{"detail":"Too many requests"}'
            response.headers["Content-Length"] = str(len(response.body))
            return response

        return response
