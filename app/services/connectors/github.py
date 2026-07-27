from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.services.connectors.base import BaseConnector, ConnectorAuthError, ConnectorDiscoveryError, ConnectorNetworkError, ConnectorRateLimitError
from app.services.connectors import registry


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class GitHubConnector(BaseConnector):
    async def connect(self) -> dict:
        self._status = {"status": "connected", "message": "GitHub connected"}
        return self._status

    async def test(self) -> dict:
        # TODO: validate GitHub token (PAT or OAuth)
        return {"success": True, "message": "GitHub connection test stub"}

    async def discover(self) -> dict:
        # TODO: list repos/branches via GitHub API
        return {"items": [], "total": 0}

    async def sync(self, options: dict | None = None) -> dict:
        job_id = str(uuid.uuid4())
        started_at = utcnow().isoformat()
        self._status = {"status": "running", "progress": 0, "started_at": started_at}
        # TODO: trigger GitHub indexing
        return {"job_id": job_id, "status": "running", "started_at": started_at}

    async def get_status(self) -> dict:
        return self._status

    async def disconnect(self) -> dict:
        self._status = {"status": "idle", "progress": 0, "message": "Disconnected"}
        # TODO: revoke tokens if necessary
        return self._status

    async def refresh(self) -> dict:
        # TODO: refresh OAuth access token
        return {"success": True, "message": "Token refreshed stub"}

    def validate(self) -> dict:
        return {"valid": True, "errors": []}

    def watch(self, poll_interval: int = 120) -> Any:
        from app.services.watchers import GitHubWatcher
        watcher = GitHubWatcher(self, poll_interval=poll_interval)
        return watcher


registry.register("github", GitHubConnector)
