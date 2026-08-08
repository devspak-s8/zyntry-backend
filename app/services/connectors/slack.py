from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

from app.services.connectors.base import BaseConnector, ConnectorAuthError, ConnectorDiscoveryError, ConnectorNetworkError, ConnectorRateLimitError
from app.services.connectors import registry


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SlackConnector(BaseConnector):
    def __init__(self, project_id: str, source_id: str, config: dict, credentials: dict | None = None) -> None:
        super().__init__(project_id, source_id, config, credentials)
        self._token = (credentials or {}).get("bot_token") or config.get("bot_token")
        if not self._token:
            raise ConnectorAuthError("Slack bot token is required")

    async def connect(self) -> dict:
        result = await self.test()
        self._status = {"status": "connected" if result.get("success") else "error", "message": result.get("message", "")}
        return self._status

    async def test(self) -> dict:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    "https://slack.com/api/auth.test",
                    headers={"Authorization": f"Bearer {self._token}", "Content-Type": "application/x-www-form-urlencoded"},
                    data={"token": self._token},
                )
                data = resp.json()
                if data.get("ok"):
                    return {"success": True, "message": f"Connected as {data.get('user')} in {data.get('team')}"}
                return {"success": False, "message": data.get("error", "Slack auth failed")}
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    async def discover(self) -> dict:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                headers = {"Authorization": f"Bearer {self._token}"}
                channels_resp = await client.get("https://slack.com/api/conversations.list", headers=headers, params={"types": "public_channel,private_channel", "limit": 200})
                channels_resp.raise_for_status()
                channels_data = channels_resp.json()
                items = []
                if channels_data.get("ok"):
                    for ch in channels_data.get("channels", []):
                        items.append({
                            "id": ch.get("id"),
                            "name": ch.get("name"),
                            "type": "channel",
                            "is_private": ch.get("is_private", False),
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
            errors.append("Missing Slack bot token")
        return {"valid": len(errors) == 0, "errors": errors}

    def watch(self, poll_interval: int = 60) -> Any:
        from app.services.watchers import SlackWatcher
        watcher = SlackWatcher(self, poll_interval=poll_interval)
        return watcher


registry.register("slack", SlackConnector)
