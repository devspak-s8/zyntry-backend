from __future__ import annotations

from typing import Any

from app.services.connectors.base import BaseConnector, ConnectorAuthError, ConnectorDiscoveryError, ConnectorNetworkError, ConnectorRateLimitError
from app.services.connectors import registry


class WebsiteConnector(BaseConnector):
    async def connect(self) -> dict:
        self._status = {"status": "connected", "message": "Website connected"}
        return self._status

    async def test(self) -> dict:
        url = self.config.get("url") or self.credentials.get("url")
        if not url:
            return {"success": False, "message": "Missing website URL"}
        return {"success": True, "message": f"Website connection test stub for {url}"}

    async def discover(self) -> dict:
        url = self.config.get("url") or self.credentials.get("url")
        return {"items": [], "total": 0, "url": url}

    async def sync(self, options: dict | None = None) -> dict:
        import uuid
        from datetime import datetime, timezone

        job_id = str(uuid.uuid4())
        started_at = datetime.now(timezone.utc).isoformat()
        self._status = {"status": "running", "progress": 0, "started_at": started_at}
        return {"job_id": job_id, "status": "running", "started_at": started_at}

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
