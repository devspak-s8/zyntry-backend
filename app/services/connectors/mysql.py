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


class MySQLConnector(BaseConnector):
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
            raise ConnectorAuthError("MySQL connection string is required")
        self._target_tables = (creds.get("tables") or config.get("tables") or "*").strip()

    def _dsn_to_kwargs(self) -> dict:
        parsed = urlparse(self._connection_string)
        return {
            "host": parsed.hostname or "localhost",
            "port": parsed.port or 3306,
            "user": parsed.username or "",
            "password": parsed.password or "",
            "db": parsed.path.lstrip("/") or "",
        }

    async def _get_connection(self):
        try:
            import aiomysql
        except ImportError as exc:
            raise ConnectorNetworkError("aiomysql is not installed") from exc
        kwargs = self._dsn_to_kwargs()
        if not kwargs["db"]:
            raise ConnectorAuthError("MySQL database name is required in the connection string")
        return await aiomysql.connect(
            host=kwargs["host"],
            port=kwargs["port"],
            user=kwargs["user"],
            password=kwargs["password"],
            db=kwargs["db"],
            connect_timeout=10,
        )

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
            conn = await self._get_connection()
            async with conn.cursor() as cursor:
                await cursor.execute("SELECT 1 AS ok")
                row = await cursor.fetchone()
            await conn.ensure_closed()
            if row and row[0] == 1:
                return {"success": True, "message": "MySQL connection successful"}
            return {"success": False, "message": "Unexpected MySQL response"}
        except ConnectorNetworkError as exc:
            return {"success": False, "message": str(exc)}
        except ConnectorAuthError as exc:
            return {"success": False, "message": str(exc)}
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    async def discover(self) -> dict:
        try:
            conn = await self._get_connection()
            async with conn.cursor() as cursor:
                await cursor.execute(
                    "SELECT table_schema, table_name FROM information_schema.tables "
                    "WHERE table_type = 'BASE TABLE' AND table_schema = DATABASE() "
                    "ORDER BY table_name"
                )
                tables = await cursor.fetchall()
            await conn.ensure_closed()
            selected = set()
            if self._target_tables and self._target_tables != "*":
                selected = {t.strip() for t in self._target_tables.split(",") if t.strip()}
            items = []
            for schema, table in tables:
                if selected and table not in selected:
                    continue
                col_conn = await self._get_connection()
                async with col_conn.cursor() as cursor:
                    await cursor.execute(
                        "SELECT column_name, data_type, is_nullable "
                        "FROM information_schema.columns "
                        "WHERE table_schema = %s AND table_name = %s "
                        "ORDER BY ordinal_position",
                        (schema, table),
                    )
                    columns = await cursor.fetchall()
                await col_conn.ensure_closed()
                items.append({
                    "schema": schema,
                    "name": table,
                    "type": "table",
                    "columns": [
                        {"name": col, "type": dtype, "nullable": nullable == "YES"}
                        for col, dtype, nullable in columns
                    ],
                })
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
        self._status = {"status": "idle", "progress": 0, "message": "Disconnected"}
        return self._status

    async def refresh(self) -> dict:
        return {"success": True, "message": "Connection remains valid"}

    def validate(self) -> dict:
        errors = []
        if not self._connection_string:
            errors.append("Missing MySQL connection string")
        return {"valid": len(errors) == 0, "errors": errors}

    def watch(self, poll_interval: int = 90) -> Any:
        return None


registry.register("mysql", MySQLConnector)
registry.register("mariadb", MySQLConnector)
registry.register("tidb", MySQLConnector)
