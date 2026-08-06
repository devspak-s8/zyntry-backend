from __future__ import annotations

from typing import Any

import httpx

from app.schemas.actions import ActionDefinition, ActionResponse
from app.services.actions.base import BaseActionProvider


class NotionActionProvider(BaseActionProvider):
    provider_name = "notion"

    def __init__(self, credentials: dict[str, Any] | None = None) -> None:
        self._token = (credentials or {}).get("token")
        self._base_url = "https://api.notion.com/v1"
        if not self._token:
            raise ValueError("Notion token is required")

    def list_actions(self) -> list[ActionDefinition]:
        return [
            ActionDefinition(name="search", description="Search workspace", provider=self.provider_name, risk="low"),
            ActionDefinition(name="get_page", description="Get a page", provider=self.provider_name, risk="low"),
            ActionDefinition(name="create_page", description="Create a page", provider=self.provider_name, risk="low"),
            ActionDefinition(name="update_page", description="Update a page", provider=self.provider_name, risk="low"),
            ActionDefinition(name="archive_page", description="Archive a page", provider=self.provider_name, risk="medium", required_permissions=["write"]),
            ActionDefinition(name="create_database", description="Create a database", provider=self.provider_name, risk="low"),
            ActionDefinition(name="query_database", description="Query a database", provider=self.provider_name, risk="low"),
            ActionDefinition(name="create_database_row", description="Insert a database row", provider=self.provider_name, risk="low"),
            ActionDefinition(name="update_database_row", description="Update a database row", provider=self.provider_name, risk="low"),
            ActionDefinition(name="append_block_children", description="Append blocks to a page", provider=self.provider_name, risk="low"),
        ]

    async def validate(self, action: str, arguments: dict[str, Any]) -> bool:
        required = {"create_page": ["parent", "title"], "create_database": ["parent", "title"], "create_database_row": ["database_id"], "update_page": ["page_id"]}
        params = required.get(action, [])
        return all(p in arguments for p in params)

    async def execute(self, action: str, arguments: dict[str, Any], context: dict[str, Any]) -> ActionResponse:
        try:
            headers = {"Authorization": f"Bearer {self._token}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
            async with httpx.AsyncClient(timeout=30) as client:
                if action == "search":
                    resp = await client.post(f"{self._base_url}/search", headers=headers, json={"query": arguments.get("query", ""), "filter": arguments.get("filter")})
                    return ActionResponse(success=True, result=resp.json())
                elif action == "get_page":
                    resp = await client.get(f"{self._base_url}/pages/{arguments['page_id']}", headers=headers)
                    return ActionResponse(success=True, result=resp.json())
                elif action == "create_page":
                    payload = {"parent": arguments["parent"], "properties": {"title": {"title": [{"text": {"content": arguments["title"]}}]}}, "children": arguments.get("children", [])}
                    resp = await client.post(f"{self._base_url}/pages", headers=headers, json=payload)
                    return ActionResponse(success=True, result=resp.json())
                elif action == "update_page":
                    payload = {"properties": arguments.get("properties", {}), "archived": arguments.get("archived", False)}
                    resp = await client.patch(f"{self._base_url}/pages/{arguments['page_id']}", headers=headers, json=payload)
                    return ActionResponse(success=True, result=resp.json())
                elif action == "archive_page":
                    resp = await client.patch(f"{self._base_url}/pages/{arguments['page_id']}", headers=headers, json={"archived": True})
                    return ActionResponse(success=True, result=resp.json())
                elif action == "create_database":
                    payload = {"parent": arguments["parent"], "title": {"title": [{"text": {"content": arguments["title"]}}]}, "properties": arguments.get("properties", {})}
                    resp = await client.post(f"{self._base_url}/databases", headers=headers, json=payload)
                    return ActionResponse(success=True, result=resp.json())
                elif action == "query_database":
                    resp = await client.post(f"{self._base_url}/databases/{arguments['database_id']}/query", headers=headers, json={"filter": arguments.get("filter"), "sorts": arguments.get("sorts", [])})
                    return ActionResponse(success=True, result=resp.json())
                elif action == "create_database_row":
                    payload = {"parent": {"database_id": arguments["database_id"]}, "properties": arguments.get("properties", {})}
                    resp = await client.post(f"{self._base_url}/pages", headers=headers, json=payload)
                    return ActionResponse(success=True, result=resp.json())
                elif action == "update_database_row":
                    payload = {"properties": arguments.get("properties", {})}
                    resp = await client.patch(f"{self._base_url}/pages/{arguments['page_id']}", headers=headers, json=payload)
                    return ActionResponse(success=True, result=resp.json())
                elif action == "append_block_children":
                    resp = await client.patch(f"{self._base_url}/blocks/{arguments['page_id']}/children", headers=headers, json={"children": arguments.get("children", [])})
                    return ActionResponse(success=True, result=resp.json())
                else:
                    return ActionResponse(success=False, error=f"Unknown action: {action}")
        except httpx.HTTPStatusError as exc:
            return ActionResponse(success=False, error=f"Notion API error: {exc.response.status_code} - {exc.response.text}")
        except Exception as exc:
            return ActionResponse(success=False, error=str(exc))
