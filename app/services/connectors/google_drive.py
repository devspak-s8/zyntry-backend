from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from app.services.connectors import registry
from app.services.connectors.base import (
    BaseConnector,
)


def utcnow() -> datetime:
    return datetime.now(UTC)


class GoogleDriveConnector(BaseConnector):
    _UNAVAILABLE_MESSAGE = (
        "Google Drive discovery and indexing is not available yet. "
        "Use an enabled document connector before selecting Google Drive."
    )

    async def connect(self) -> dict:
        self._status = {"status": "unavailable", "message": self._UNAVAILABLE_MESSAGE}
        return self._status

    async def test(self) -> dict:
        return {
            "success": False,
            "status": "unsupported",
            "code": "connector_not_implemented",
            "message": self._UNAVAILABLE_MESSAGE,
        }

    async def discover(self) -> dict:
        return {
            "items": [],
            "total": 0,
            "status": "unsupported",
            "error": self._UNAVAILABLE_MESSAGE,
        }

    async def sync(self, options: dict | None = None) -> dict:
        job_id = str(uuid.uuid4())
        started_at = utcnow().isoformat()
        self._status = {
            "status": "unavailable",
            "progress": 0,
            "started_at": started_at,
            "message": self._UNAVAILABLE_MESSAGE,
        }
        return {
            "job_id": job_id,
            "status": "unsupported",
            "started_at": started_at,
            "error": self._UNAVAILABLE_MESSAGE,
        }

    async def get_status(self) -> dict:
        return self._status

    async def disconnect(self) -> dict:
        self._status = {"status": "idle", "progress": 0, "message": "Disconnected"}
        return self._status

    async def refresh(self) -> dict:
        return {
            "success": False,
            "status": "unsupported",
            "code": "connector_not_implemented",
            "message": self._UNAVAILABLE_MESSAGE,
        }

    def validate(self) -> dict:
        return {"valid": False, "errors": [self._UNAVAILABLE_MESSAGE]}

    def watch(self, poll_interval: int = 180) -> Any:
        from app.services.watchers import GoogleDriveWatcher
        watcher = GoogleDriveWatcher(self, poll_interval=poll_interval)
        return watcher


registry.register("google_drive", GoogleDriveConnector)
registry.register("gdrive", GoogleDriveConnector)
