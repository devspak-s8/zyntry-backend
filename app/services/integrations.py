from __future__ import annotations

from typing import Any, Literal

from app.repositories import UnitOfWork
from app.services.tools import ToolService

ConnectionPurpose = Literal["source", "tool", "both"]
SOURCE_CONNECTORS = {"github", "notion", "slack"}


class IntegrationService:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def materialize_oauth_connection(
        self,
        *,
        provider: str,
        project_id: str,
        oauth_connection_id: str,
        display_name: str,
        purpose: ConnectionPurpose,
        source_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        provider = provider.lower()
        tool_id: str | None = None
        source_id: str | None = None

        if purpose in {"tool", "both"}:
            tool = await ToolService(self.uow).connect_oauth_catalog_tool(
                connector_key=provider,
                project_id=project_id,
                display_name=display_name,
                oauth_connection_id=oauth_connection_id,
            )
            tool_id = tool["tool_id"]

        if purpose in {"source", "both"}:
            if provider not in SOURCE_CONNECTORS:
                raise ValueError(f"{provider} is not available as a knowledge source")
            sources = await self.uow.knowledge_sources.get_by_project(project_id)
            source = next(
                (
                    item
                    for item in sources
                    if item.source_type == provider
                    and (item.config or {}).get("oauth_connection_id")
                    == oauth_connection_id
                ),
                None,
            )
            config = {
                **(source.config if source else {}),
                **(source_config or {}),
                "oauth_connection_id": oauth_connection_id,
            }
            if source is None:
                source = await self.uow.knowledge_sources.create(
                    project_id=project_id,
                    source_type=provider,
                    display_name=display_name,
                    config=config,
                    sync_frequency="manual",
                    status="ready",
                    connection_status="connected",
                    metadata_={"oauth_managed": True},
                    credentials_encrypted=None,
                )
            else:
                source = await self.uow.knowledge_sources.update(
                    source,
                    display_name=display_name,
                    config=config,
                    status="ready",
                    connection_status="connected",
                    is_active=True,
                    last_error=None,
                )
            await self.uow.commit()
            source_id = str(source.id)

        return {
            "provider": provider,
            "purpose": purpose,
            "oauth_connection_id": oauth_connection_id,
            "tool_id": tool_id,
            "source_id": source_id,
        }
