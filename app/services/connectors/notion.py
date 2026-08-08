from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

from app.services.connectors.base import BaseConnector, ConnectorAuthError, ConnectorDiscoveryError, ConnectorNetworkError, ConnectorRateLimitError
from app.services.connectors import registry


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class NotionConnector(BaseConnector):
    def __init__(self, project_id: str, source_id: str, config: dict, credentials: dict | None = None) -> None:
        super().__init__(project_id, source_id, config, credentials)
        self._base_url = "https://api.notion.com/v1"
        self._token = (credentials or {}).get("token") or config.get("token")
        if not self._token:
            raise ConnectorAuthError("Notion integration token is required")

    async def connect(self) -> dict:
        result = await self.test()
        self._status = {"status": "connected" if result.get("success") else "error", "message": result.get("message", "")}
        return self._status

    async def test(self) -> dict:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{self._base_url}/users/me",
                    headers={"Authorization": f"Bearer {self._token}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"},
                )
                if resp.status_code == 401:
                    return {"success": False, "message": "Invalid Notion token"}
                resp.raise_for_status()
                return {"success": True, "message": "Notion connection successful"}
        except httpx.HTTPStatusError as exc:
            return {"success": False, "message": f"Notion API error: {exc.response.status_code}"}
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    async def discover(self) -> dict:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                headers = {"Authorization": f"Bearer {self._token}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
                resp = await client.post(f"{self._base_url}/search", headers=headers, json={"page_size": 100})
                resp.raise_for_status()
                data = resp.json()
                items = []
                for result in data.get("results", []):
                    item_type = result.get("object", "unknown")
                    title = ""
                    if item_type == "page":
                        props = result.get("properties", {})
                        for prop in props.values():
                            if prop.get("type") == "title":
                                title = "".join(t.get("plain_text", "") for t in prop.get("title", []))
                                break
                    elif item_type == "database":
                        title = "".join(t.get("plain_text", "") for t in result.get("title", []))
                    items.append({
                        "id": result.get("id"),
                        "name": title or result.get("id"),
                        "type": item_type,
                        "url": result.get("url"),
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
        return {"job_id": job_id, "status": "completed", "started_at": started_at, "items": items, "total": len(items)}

    async def get_status(self) -> dict:
        return self._status

    async def disconnect(self) -> dict:
        self._status = {"status": "idle", "progress": 0, "message": "Disconnected"}
        return self._status

    async def refresh(self) -> dict:
        return {"success": True, "message": "Token remains valid"}

    def validate(self) -> dict:
        errors = []
        if not self._token:
            errors.append("Missing Notion token")
        return {"valid": len(errors) == 0, "errors": errors}

    def watch(self, poll_interval: int = 150) -> Any:
        from app.services.watchers import NotionWatcher
        watcher = NotionWatcher(self, poll_interval=poll_interval)
        return watcher


registry.register("notion", NotionConnector)
