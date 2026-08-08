from __future__ import annotations

from typing import Any

import httpx

from app.services.connectors.base import BaseConnector, ConnectorAuthError, ConnectorDiscoveryError, ConnectorNetworkError, ConnectorRateLimitError
from app.services.connectors import registry


class WebsiteConnector(BaseConnector):
    async def connect(self) -> dict:
        result = await self.test()
        self._status = {"status": "connected" if result.get("success") else "error", "message": result.get("message", "")}
        return self._status

    async def test(self) -> dict:
        url = self.config.get("url") or self.credentials.get("url")
        if not url:
            return {"success": False, "message": "Missing website URL"}
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                resp = await client.get(url)
                if resp.status_code < 400:
                    return {"success": True, "message": f"Website reachable: {url}", "status_code": resp.status_code}
                return {"success": False, "message": f"Website returned {resp.status_code}", "status_code": resp.status_code}
        except httpx.HTTPError as exc:
            return {"success": False, "message": str(exc)}
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    async def discover(self) -> dict:
        url = self.config.get("url") or self.credentials.get("url")
        if not url:
            return {"items": [], "total": 0}
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                resp = await client.get(url)
                text = resp.text
                return {"items": [{"url": url, "title": url, "content_length": len(text)}], "total": 1}
        except Exception as exc:
            return {"items": [], "total": 0, "error": str(exc)}

    async def sync(self, options: dict | None = None) -> dict:
        import uuid
        from datetime import datetime, timezone

        job_id = str(uuid.uuid4())
        started_at = datetime.now(timezone.utc).isoformat()
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
        return {"success": True, "message": "Refresh stub"}

    def validate(self) -> dict:
        url = self.config.get("url") or self.credentials.get("url")
        errors = []
        if not url:
            errors.append("Missing website URL")
        return {"valid": len(errors) == 0, "errors": errors}

    def watch(self, poll_interval: int = 120) -> Any:
        return None


registry.register("website", WebsiteConnector)
