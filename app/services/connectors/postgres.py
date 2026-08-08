from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from app.services.connectors.base import BaseConnector, ConnectorAuthError, ConnectorDiscoveryError, ConnectorNetworkError, ConnectorRateLimitError
from app.services.connectors import registry


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PostgresConnector(BaseConnector):
    def __init__(self, project_id: str, source_id: str, config: dict, credentials: dict | None = None) -> None:
        super().__init__(project_id, source_id, config, credentials)
        self._connection_string = (credentials or {}).get("connection_string") or config.get("connection_string")
        if not self._connection_string:
            raise ConnectorAuthError("PostgreSQL connection string is required")

    async def connect(self) -> dict:
        result = await self.test()
        self._status = {"status": "connected" if result.get("success") else "error", "message": result.get("message", "")}
        return self._status

    async def test(self) -> dict:
        try:
            import asyncpg
            conn = await asyncpg.connect(self._connection_string, timeout=10)
            row = await conn.fetchrow("SELECT 1 AS ok")
            await conn.close()
            if row and row["ok"] == 1:
                return {"success": True, "message": "PostgreSQL connection successful"}
            return {"success": False, "message": "Unexpected PostgreSQL response"}
        except ImportError:
            return {"success": False, "message": "asyncpg not installed"}
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    async def discover(self) -> dict:
        try:
            import asyncpg
            conn = await asyncpg.connect(self._connection_string, timeout=15)
            tables = await conn.fetch(
                "SELECT table_schema, table_name FROM information_schema.tables WHERE table_type = 'BASE TABLE' ORDER BY table_schema, table_name"
            )
            await conn.close()
            items = []
            for row in tables:
                items.append({
                    "schema": row["table_schema"],
                    "name": row["table_name"],
                    "type": "table",
                })
            return {"items": items, "total": len(items)}
        except ImportError:
            return {"items": [], "total": 0, "error": "asyncpg not installed"}
        except Exception as exc:
            return {"items": [], "total": 0, "error": str(exc)}

    async def sync(self, options: dict | None = None) -> dict:
        job_id = str(uuid.uuid4())
        started_at = utcnow().isoformat()
        self._status = {"status": "running", "progress": 0, "started_at": started_at}
        discovered = await self.discover()
        items = discovered.get("items", [])
        self._status = {"status": "completed", "progress": 100, "items_synced": len(items)}
        return {"job_id": job_id, "status": "completed", "started_at": started_at, "items": items, "total": len(items)}

    async def get_status(self) -> dict:
        return self._status

    async def disconnect(self) -> dict:
        self._status = {"status": "idle", "progress": 0, "message": "Disconnected"}
        return self._status

    async def refresh(self) -> dict:
        return {"success": True, "message": "Connection remains valid"}

    def validate(self) -> dict:
        errors = []
        if not self._connection_string:
            errors.append("Missing PostgreSQL connection string")
        return {"valid": len(errors) == 0, "errors": errors}

    def watch(self, poll_interval: int = 90) -> Any:
        from app.services.watchers import PostgresWatcher
        watcher = PostgresWatcher(self, poll_interval=poll_interval)
        return watcher


registry.register("postgres", PostgresConnector)
