from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from app.services.connectors import registry
from app.services.connectors.base import (
    BaseConnector,
    ConnectorAuthError,
    ConnectorNetworkError,
)


def utcnow() -> datetime:
    return datetime.now(UTC)


class RedisConnector(BaseConnector):
    INDEXING_STRATEGY = (
        "Scan keys with Redis SCAN (avoid KEYS), treat each key's value as a document. "
        "Use config.tables as a comma-separated list of key patterns (glob-style, e.g. user:*). "
        "If tables is '*' or empty, index all string keys."
    )

    def __init__(
        self,
        project_id: str,
        source_id: str,
        config: dict,
        credentials: dict | None = None,
    ) -> None:
        super().__init__(project_id, source_id, config, credentials)
        creds = credentials or {}
        self._connection_string = creds.get("connection_string") or config.get("connection_string")
        if not self._connection_string:
            raise ConnectorAuthError("Redis connection string is required")
        self._key_patterns = (creds.get("tables") or config.get("tables") or "*").strip()
        self._client = None

    async def _get_client(self):
        if self._client is None:
            try:
                import redis.asyncio as aioredis
            except ImportError as exc:
                raise ConnectorNetworkError("redis is not installed") from exc
            self._client = aioredis.from_url(
                self._connection_string,
                decode_responses=True,
                socket_connect_timeout=10,
                socket_timeout=10,
            )
        return self._client

    async def connect(self) -> dict:
        result = await self.test()
        connected = result.get("success")
        self._status = {
            "status": "connected" if connected else "error",
            "message": result.get("message", ""),
        }
        return self._status

    async def test(self) -> dict:
        try:
            client = await self._get_client()
            await client.ping()
            return {"success": True, "message": "Redis connection successful"}
        except ImportError as exc:
            return {"success": False, "message": str(exc)}
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    async def discover(self) -> dict:
        try:
            client = await self._get_client()
            patterns = []
            if not self._key_patterns or self._key_patterns == "*":
                patterns = ["*"]
            else:
                patterns = [p.strip() for p in self._key_patterns.split(",") if p.strip()]
            seen = set()
            items = []
            cursor = 0
            while True:
                cursor, keys = await client.scan(cursor=cursor, match=patterns[0], count=500)
                for key in keys:
                    if key in seen:
                        continue
                    seen.add(key)
                    value = None
                    try:
                        value = await client.get(key)
                    except Exception:
                        pass
                    if value is None:
                        try:
                            value = await client.lrange(key, 0, -1)
                        except Exception:
                            value = None
                    if isinstance(value, str):
                        value_type = "string"
                    elif isinstance(value, list):
                        value_type = "list"
                    else:
                        value_type = "unknown"
                    items.append({
                        "name": key,
                        "type": "key",
                        "value_type": value_type,
                        "value_preview": value if isinstance(value, (str, list)) else None,
                    })
                if cursor == 0:
                    break
            return {"items": items, "total": len(items)}
        except ImportError as exc:
            return {"items": [], "total": 0, "error": str(exc)}
        except Exception as exc:
            return {"items": [], "total": 0, "error": str(exc)}

    async def sync(self, options: dict | None = None) -> dict:
        job_id = str(uuid.uuid4())
        started_at = utcnow().isoformat()
        self._status = {"status": "running", "progress": 0, "started_at": started_at}
        discovered = await self.discover()
        items = discovered.get("items", [])
        self._status = {"status": "completed", "progress": 100, "items_synced": len(items)}
        return {
            "job_id": job_id,
            "status": "completed",
            "started_at": started_at,
            "items": items,
            "total": len(items),
        }

    async def get_status(self) -> dict:
        return self._status

    async def disconnect(self) -> dict:
        if self._client:
            await self._client.aclose()
            self._client = None
        self._status = {"status": "idle", "progress": 0, "message": "Disconnected"}
        return self._status

    async def refresh(self) -> dict:
        return {"success": True, "message": "Connection remains valid"}

    def validate(self) -> dict:
        errors = []
        if not self._connection_string:
            errors.append("Missing Redis connection string")
        return {"valid": len(errors) == 0, "errors": errors}

    def watch(self, poll_interval: int = 90) -> Any:
        return None


registry.register("redis", RedisConnector)
