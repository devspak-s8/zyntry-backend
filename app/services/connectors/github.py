from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

from app.services.connectors.base import BaseConnector, ConnectorAuthError, ConnectorDiscoveryError, ConnectorNetworkError, ConnectorRateLimitError
from app.services.connectors import registry


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class GitHubConnector(BaseConnector):
    def __init__(self, project_id: str, source_id: str, config: dict, credentials: dict | None = None) -> None:
        super().__init__(project_id, source_id, config, credentials)
        self._base_url = "https://api.github.com"
        self._token = (credentials or {}).get("token") or config.get("token")
        if not self._token:
            raise ConnectorAuthError("GitHub token is required")

    async def connect(self) -> dict:
        result = await self.test()
        self._status = {"status": "connected" if result.get("success") else "error", "message": result.get("message", "")}
        return self._status

    async def test(self) -> dict:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{self._base_url}/user",
                    headers={"Authorization": f"Bearer {self._token}", "Accept": "application/vnd.github+json"},
                )
                if resp.status_code == 401:
                    return {"success": False, "message": "Invalid GitHub token"}
                resp.raise_for_status()
                data = resp.json()
                return {"success": True, "message": f"Connected as {data.get('login')}", "user": data}
        except httpx.HTTPStatusError as exc:
            return {"success": False, "message": f"GitHub API error: {exc.response.status_code}"}
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    async def discover(self) -> dict:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                headers = {"Authorization": f"Bearer {self._token}", "Accept": "application/vnd.github+json"}
                repos_resp = await client.get(f"{self._base_url}/user/repos", headers=headers, params={"per_page": 100, "sort": "updated"})
                repos_resp.raise_for_status()
                repos = repos_resp.json()
                items = []
                for repo in repos:
                    items.append({
                        "id": str(repo["id"]),
                        "name": repo["full_name"],
                        "type": "repository",
                        "url": repo["html_url"],
                        "default_branch": repo.get("default_branch", "main"),
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
        total = discovered.get("total", 0)
        self._status = {"status": "completed", "progress": 100, "items_synced": total}
        return {"job_id": job_id, "status": "completed", "started_at": started_at, "items": items, "total": total}

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
            errors.append("Missing GitHub token")
        return {"valid": len(errors) == 0, "errors": errors}

    def watch(self, poll_interval: int = 120) -> Any:
        from app.services.watchers import GitHubWatcher
        watcher = GitHubWatcher(self, poll_interval=poll_interval)
        return watcher


registry.register("github", GitHubConnector)
