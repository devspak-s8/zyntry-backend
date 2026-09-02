from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from app.services.connectors import registry
from app.services.connectors.base import (
    BaseConnector,
    ConnectorAuthError,
    ConnectorNetworkError,
)


def utcnow() -> datetime:
    return datetime.now(UTC)


class SQLiteConnector(BaseConnector):
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
            raise ConnectorAuthError("SQLite/Turso connection string is required")
        self._auth_token = creds.get("auth_token") or config.get("auth_token")
        self._target_tables = (creds.get("tables") or config.get("tables") or "*").strip()
        self._client = None

    async def _get_client(self):
        if self._client is None:
            try:
                from libsql_experimental import create_client
            except ImportError as exc:
                raise ConnectorNetworkError("libsql-experimental is not installed") from exc
            parsed = urlparse(self._connection_string)
            url = self._connection_string
            auth_token = self._auth_token
            if parsed.scheme == "http" and not auth_token:
                if parsed.hostname and parsed.hostname.endswith(".turso.io"):
                    raise ConnectorAuthError(
                        "Turso auth token is required for remote libSQL connections"
                    )
            self._client = create_client(url=url, auth_token=auth_token)
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
            await client.execute("SELECT 1")
            return {"success": True, "message": "SQLite/Turso connection successful"}
        except ImportError as exc:
            return {"success": False, "message": str(exc)}
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    async def discover(self) -> dict:
        try:
            client = await self._get_client()
            rows = await client.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "ORDER BY name"
            )
            selected = set()
            if self._target_tables and self._target_tables != "*":
                selected = {t.strip() for t in self._target_tables.split(",") if t.strip()}
            items = []
            for row in rows:
                name = row[0] if isinstance(row, (list, tuple)) else row.get("name")
                if not name:
                    continue
                if selected and name not in selected:
                    continue
                col_rows = await client.execute(f"PRAGMA table_info('{name}')")
                columns = []
                for col in col_rows:
                    unpacked = col if isinstance(col, (list, tuple)) else col.values()
                    cid, col_name, col_type, notnull, default_val, pk = unpacked
                    columns.append({
                        "name": col_name,
                        "type": col_type or "TEXT",
                        "nullable": not notnull,
                        "primary_key": bool(pk),
                    })
                items.append({"schema": "main", "name": name, "type": "table", "columns": columns})
            return {"items": items, "total": len(items)}
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
            try:
                await self._client.close()
            except Exception:
                pass
            self._client = None
        self._status = {"status": "idle", "progress": 0, "message": "Disconnected"}
        return self._status

    async def refresh(self) -> dict:
        return {"success": True, "message": "Connection remains valid"}

    def validate(self) -> dict:
        errors = []
        if not self._connection_string:
            errors.append("Missing SQLite/Turso connection string")
        return {"valid": len(errors) == 0, "errors": errors}

    def watch(self, poll_interval: int = 90) -> Any:
        return None


registry.register("sqlite", SQLiteConnector)
registry.register("spatialite", SQLiteConnector)
