from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

from app.services.connectors.base import BaseConnector, ConnectorAuthError, ConnectorDiscoveryError, ConnectorNetworkError, ConnectorRateLimitError
from app.services.connectors import registry


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MCPConnector(BaseConnector):
    def __init__(self, project_id: str, source_id: str, config: dict, credentials: dict | None = None) -> None:
        super().__init__(project_id, source_id, config, credentials)
        self._base_url = (config.get("url") or credentials.get("url") or "").rstrip("/")
        self._api_key = (credentials or {}).get("api_key") or config.get("api_key")
        if not self._base_url:
            raise ConnectorAuthError("MCP server URL is required")

    async def connect(self) -> dict:
        result = await self.test()
        self._status = {"status": "connected" if result.get("success") else "error", "message": result.get("message", "")}
        return self._status

    async def test(self) -> dict:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{self._base_url}/health",
                    headers=self._headers(),
                )
                if resp.status_code == 200:
                    return {"success": True, "message": "MCP server reachable"}
                return {"success": False, "message": f"MCP server returned {resp.status_code}"}
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    async def discover(self) -> dict:
        try:
            tools = await self._list_tools()
            return {"items": tools, "total": len(tools)}
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
        return {"success": True, "message": "MCP session remains valid"}

    async def list_tools(self) -> list[dict[str, Any]]:
        return await self._list_tools()

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return await self._post("/tools/call", {"name": name, "arguments": arguments})

    def validate(self) -> dict:
        errors = []
        if not self._base_url:
            errors.append("Missing MCP server URL")
        return {"valid": len(errors) == 0, "errors": errors}

    def watch(self, poll_interval: int = 120) -> Any:
        return None

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    async def _list_tools(self) -> list[dict[str, Any]]:
        data = await self._post("/tools/list", {})
        tools = []
        for tool in data.get("tools", []):
            tools.append({
                "id": tool.get("name"),
                "name": tool.get("name"),
                "description": tool.get("description"),
                "schema": tool.get("inputSchema", {}),
                "implementation": f"mcp://{self._base_url}/tools/call",
            })
        return tools

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{self._base_url}{path}", json=payload, headers=self._headers())
            resp.raise_for_status()
            return resp.json()


registry.register("mcp", MCPConnector)
