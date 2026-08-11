from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from app.repositories import UnitOfWork
from app.schemas.tools import ToolCreate, ToolUpdate
from app.services.connectors import registry
from app.services.encryption import encrypt_value


TOOL_CATALOG: tuple[dict[str, Any], ...] = (
    {"key": "github", "name": "GitHub", "description": "Connect repositories and code metadata.", "category": "Development", "auth_type": "oauth", "credential_fields": [], "config_fields": []},
    {"key": "gitlab", "name": "GitLab", "description": "Connect GitLab projects and repositories.", "category": "Development", "auth_type": "token", "credential_fields": ["token"], "config_fields": ["base_url"]},
    {"key": "notion", "name": "Notion", "description": "Connect Notion pages and databases.", "category": "Knowledge", "auth_type": "oauth", "credential_fields": [], "config_fields": []},
    {"key": "google_drive", "name": "Google Drive", "description": "Connect files stored in Google Drive.", "category": "Knowledge", "auth_type": "oauth", "credential_fields": ["access_token"], "config_fields": []},
    {"key": "slack", "name": "Slack", "description": "Connect Slack workspaces and channels.", "category": "Communication", "auth_type": "oauth", "credential_fields": ["token"], "config_fields": []},
    {"key": "postgres", "name": "PostgreSQL", "description": "Connect a PostgreSQL-compatible database.", "category": "Database", "auth_type": "connection_string", "credential_fields": ["connection_string"], "config_fields": []},
    {"key": "mysql", "name": "MySQL", "description": "Connect a MySQL-compatible database.", "category": "Database", "auth_type": "connection_string", "credential_fields": ["connection_string"], "config_fields": []},
    {"key": "mongodb", "name": "MongoDB", "description": "Connect a MongoDB database.", "category": "Database", "auth_type": "connection_string", "credential_fields": ["connection_string"], "config_fields": ["database"]},
    {"key": "redis", "name": "Redis", "description": "Connect a Redis data store.", "category": "Database", "auth_type": "connection_string", "credential_fields": ["connection_string"], "config_fields": []},
    {"key": "sqlite", "name": "SQLite", "description": "Connect an SQLite database available to the runtime.", "category": "Database", "auth_type": "path", "credential_fields": [], "config_fields": ["path"]},
    {"key": "s3", "name": "Amazon S3", "description": "Connect an S3 bucket.", "category": "Storage", "auth_type": "credentials", "credential_fields": ["access_key_id", "secret_access_key"], "config_fields": ["bucket", "region"]},
    {"key": "website", "name": "Website", "description": "Connect a public website URL.", "category": "Web", "auth_type": "none", "credential_fields": [], "config_fields": ["url"]},
    {"key": "mcp", "name": "MCP Server", "description": "Connect tools exposed by a Model Context Protocol server.", "category": "API", "auth_type": "token", "credential_fields": ["api_key"], "config_fields": ["url"]},
)
_CATALOG_BY_KEY = {item["key"]: item for item in TOOL_CATALOG}
_LIVE_CONNECTORS = {
    "github",
    "mcp",
    "mongodb",
    "mysql",
    "notion",
    "postgres",
    "redis",
    "slack",
    "sqlite",
    "website",
}
_OAUTH_CONNECTORS = {"github", "notion", "slack"}
_INTERNAL_CONNECTION_KEY = "_zyntry_connection"


class ToolService:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def list_tools(self, project_id: str | None = None) -> list[dict]:
        if project_id:
            tools = await self.uow.tools.get_by_project(project_id)
        else:
            tools = []
        return [
            {
                "id": str(t.id),
                "name": t.name,
                "description": t.description,
                "schema": self._public_schema(t.schema),
                "implementation": t.implementation,
                "project_id": str(t.project_id) if t.project_id else None,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in tools
        ]

    async def create_tool(self, data: ToolCreate) -> dict:
        tool = await self.uow.tools.create(
            name=data.name,
            description=data.description,
            schema=data.schema,
            implementation=data.implementation,
            project_id=data.project_id,
        )
        await self.uow.commit()
        return {
            "id": str(tool.id),
            "name": tool.name,
            "description": tool.description,
            "schema": tool.schema,
            "implementation": tool.implementation,
            "project_id": str(tool.project_id) if tool.project_id else None,
        }

    async def update_tool(self, tool_id: str, data: ToolUpdate) -> dict:
        tool = await self.uow.tools.get(tool_id)
        if not tool:
            raise ValueError("Tool not found")
        update_data = data.model_dump(exclude_unset=True)
        updated = await self.uow.tools.update(tool, **update_data)
        await self.uow.commit()
        return {
            "id": str(updated.id),
            "name": updated.name,
            "description": updated.description,
            "schema": updated.schema,
            "implementation": updated.implementation,
        }

    async def delete_tool(self, tool_id: str) -> None:
        tool = await self.uow.tools.get(tool_id)
        if not tool:
            raise ValueError("Tool not found")
        await self.uow.tools.delete(tool)
        await self.uow.commit()

    @staticmethod
    def catalog() -> list[dict[str, Any]]:
        supported = set(registry.list_supported())
        return [
            dict(item)
            for item in TOOL_CATALOG
            if item["key"] in supported and item["key"] in _LIVE_CONNECTORS
        ]

    @staticmethod
    def _public_schema(schema: dict[str, Any] | None) -> dict[str, Any]:
        public = dict(schema or {})
        connection = public.get(_INTERNAL_CONNECTION_KEY)
        if isinstance(connection, dict):
            safe_connection = dict(connection)
            safe_connection.pop("credentials_encrypted", None)
            safe_connection.pop("config", None)
            public[_INTERNAL_CONNECTION_KEY] = safe_connection
        return public

    async def connect_catalog_tool(
        self,
        connector_key: str,
        project_id: str,
        display_name: str | None,
        config: dict[str, Any],
        credentials: dict[str, Any],
    ) -> dict[str, Any]:
        key = connector_key.lower()
        catalog_item = _CATALOG_BY_KEY.get(key)
        if (
            catalog_item is None
            or key not in registry.list_supported()
            or key not in _LIVE_CONNECTORS
        ):
            raise ValueError("Unsupported tool connector")
        if key in _OAUTH_CONNECTORS:
            raise ValueError("This connector must be connected with OAuth")

        tools = await self.uow.tools.get_by_project(project_id)
        existing = next(
            (tool for tool in tools if (tool.schema or {}).get(_INTERNAL_CONNECTION_KEY, {}).get("connector") == key),
            None,
        )
        try:
            connector = registry.create(
                key,
                project_id=project_id,
                source_id=str(existing.id) if existing else "pending",
                config=config,
                credentials=credentials,
            )
            test_result = await connector.test()
        except Exception as exc:
            test_result = {"success": False, "message": str(exc)}

        now = datetime.now(UTC)
        connection = {
            "connector": key,
            "status": "connected" if test_result.get("success") else "error",
            "message": test_result.get("message"),
            "tested_at": now.isoformat(),
            "credentials_encrypted": encrypt_value(json.dumps(credentials)) if credentials else None,
            "config": config,
        }
        public_schema = {
            _INTERNAL_CONNECTION_KEY: connection,
            "type": "connector",
        }
        if existing:
            tool = await self.uow.tools.update(
                existing,
                name=display_name or catalog_item["name"],
                description=catalog_item["description"],
                schema=public_schema,
                implementation=f"connector://{key}",
            )
        else:
            tool = await self.uow.tools.create(
                name=display_name or catalog_item["name"],
                description=catalog_item["description"],
                schema=public_schema,
                implementation=f"connector://{key}",
                project_id=project_id,
            )
        await self.uow.commit()
        return self._connection_status(tool)

    async def connect_oauth_catalog_tool(
        self,
        connector_key: str,
        project_id: str,
        display_name: str,
        oauth_connection_id: str,
    ) -> dict[str, Any]:
        key = connector_key.lower()
        catalog_item = _CATALOG_BY_KEY.get(key)
        if catalog_item is None or key not in _OAUTH_CONNECTORS:
            raise ValueError("Unsupported OAuth tool connector")
        tools = await self.uow.tools.get_by_project(project_id)
        existing = next(
            (tool for tool in tools if (tool.schema or {}).get(_INTERNAL_CONNECTION_KEY, {}).get("connector") == key),
            None,
        )
        connection = {
            "connector": key,
            "status": "connected",
            "message": f"Connected with {catalog_item['name']} OAuth",
            "tested_at": datetime.now(UTC).isoformat(),
            "oauth_connection_id": oauth_connection_id,
        }
        schema = {_INTERNAL_CONNECTION_KEY: connection, "type": "connector"}
        if existing:
            tool = await self.uow.tools.update(
                existing,
                name=display_name or catalog_item["name"],
                description=catalog_item["description"],
                schema=schema,
                implementation=f"connector://{key}",
            )
        else:
            tool = await self.uow.tools.create(
                name=display_name or catalog_item["name"],
                description=catalog_item["description"],
                schema=schema,
                implementation=f"connector://{key}",
                project_id=project_id,
            )
        await self.uow.commit()
        return self._connection_status(tool)

    async def get_catalog_tool_status(self, connector_key: str, project_id: str) -> dict[str, Any]:
        key = connector_key.lower()
        if key not in _CATALOG_BY_KEY:
            raise ValueError("Unsupported tool connector")
        tools = await self.uow.tools.get_by_project(project_id)
        tool = next(
            (item for item in tools if (item.schema or {}).get(_INTERNAL_CONNECTION_KEY, {}).get("connector") == key),
            None,
        )
        if tool is None:
            return {
                "connector": key,
                "project_id": project_id,
                "connected": False,
                "status": "not_connected",
                "message": None,
                "tool_id": None,
                "display_name": None,
                "tested_at": None,
            }
        return self._connection_status(tool)

    @staticmethod
    def _connection_status(tool: Any) -> dict[str, Any]:
        connection = (tool.schema or {}).get(_INTERNAL_CONNECTION_KEY, {})
        tested_at = connection.get("tested_at")
        return {
            "connector": connection.get("connector", ""),
            "project_id": str(tool.project_id),
            "connected": connection.get("status") == "connected",
            "status": connection.get("status", "not_connected"),
            "message": connection.get("message"),
            "tool_id": str(tool.id),
            "display_name": tool.name,
            "tested_at": datetime.fromisoformat(tested_at) if tested_at else None,
        }
