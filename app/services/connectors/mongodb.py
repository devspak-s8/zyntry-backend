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


class MongoDBConnector(BaseConnector):
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
            raise ConnectorAuthError("MongoDB connection string is required")
        self._target_collections = (creds.get("tables") or config.get("tables") or "*").strip()
        self._client = None
        self._db_name = self._extract_db_name()

    def _extract_db_name(self) -> str | None:
        try:
            parsed = self._connection_string.split("?", 1)[0]
            if "/" in parsed:
                return parsed.rsplit("/", 1)[1] or None
        except Exception:
            pass
        return None

    async def _get_client(self):
        if self._client is None:
            try:
                from motor.motor_asyncio import AsyncIOMotorClient
            except ImportError as exc:
                raise ConnectorNetworkError("motor is not installed") from exc
            self._client = AsyncIOMotorClient(
                self._connection_string,
                serverSelectionTimeoutMS=10000,
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
            await client.admin.command("ping")
            return {"success": True, "message": "MongoDB connection successful"}
        except ImportError as exc:
            return {"success": False, "message": str(exc)}
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    async def discover(self) -> dict:
        try:
            client = await self._get_client()
            db = client[self._db_name] if self._db_name else client.get_default_database()
            if db is None:
                return {
                    "items": [],
                    "total": 0,
                    "error": "Database name not provided in connection string",
                }
            selected = set()
            if self._target_collections and self._target_collections != "*":
                selected = {t.strip() for t in self._target_collections.split(",") if t.strip()}
            collections = await db.list_collection_names()
            items = []
            for name in collections:
                if selected and name not in selected:
                    continue
                sample = ""
                try:
                    doc = await db[name].find_one()
                    if doc:
                        import json
                        sample = json.dumps(doc, default=str)
                except Exception:
                    pass
                items.append({
                    "name": name,
                    "type": "collection",
                    "sample_document": sample,
                })
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
            self._client.close()
            self._client = None
        self._status = {"status": "idle", "progress": 0, "message": "Disconnected"}
        return self._status

    async def refresh(self) -> dict:
        return {"success": True, "message": "Connection remains valid"}

    def validate(self) -> dict:
        errors = []
        if not self._connection_string:
            errors.append("Missing MongoDB connection string")
        return {"valid": len(errors) == 0, "errors": errors}

    def watch(self, poll_interval: int = 90) -> Any:
        return None


registry.register("mongodb", MongoDBConnector)
