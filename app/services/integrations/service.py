from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from app.models.integrations import RuntimeIntegration
from app.repositories import UnitOfWork
from app.schemas.integrations import IntegrationDefinitionRead, RuntimeIntegrationCreate, RuntimeIntegrationUpdate
from app.services.integrations.definitions import integration_registry
from app.services.tools import ToolService

ConnectionPurpose = Literal["source", "tool", "both"]
SOURCE_CONNECTORS = {"github", "notion", "slack"}


class IntegrationService:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    def list_definitions(
        self,
        category: str | None = None,
        status: str | None = None,
        search: str | None = None,
    ) -> list[IntegrationDefinitionRead]:
        defs = integration_registry.list_all(category=category, status=status, search=search)
        return [IntegrationDefinitionRead(**d.to_dict()) for d in defs]

    def get_definition(self, slug_or_id: str) -> IntegrationDefinitionRead | None:
        defn = integration_registry.get(slug_or_id)
        if defn is None:
            return None
        return IntegrationDefinitionRead(**defn.to_dict())

    async def list_runtime_integrations(self, runtime_id: str | UUID) -> list[RuntimeIntegration]:
        rid = UUID(str(runtime_id)) if isinstance(runtime_id, str) else runtime_id
        return await self.uow.runtime_integrations.get_by_runtime(rid)

    async def enable_runtime_integration(
        self,
        runtime_id: str | UUID,
        data: RuntimeIntegrationCreate,
        user_id: UUID | None = None,
    ) -> RuntimeIntegration:
        rid = UUID(str(runtime_id)) if isinstance(runtime_id, str) else runtime_id

        # Validate runtime exists and user has permission
        runtime = await self.uow.runtimes.get(rid)
        if runtime is None:
            raise ValueError(f"Runtime '{runtime_id}' not found")
        if user_id and runtime.user_id != user_id:
            raise PermissionError("Unauthorized to modify this runtime")

        defn = integration_registry.get(data.integration_slug)
        if defn is None:
            raise ValueError(f"Integration '{data.integration_slug}' is not supported")
        data.integration_slug = defn.slug

        if defn.status not in ("available", "beta"):
            raise ValueError(
                f"Integration '{data.integration_slug}' is currently '{defn.status}' and cannot be enabled on active runtimes"
            )

        is_hybrid = data.connection_mode == "hybrid"
        supports_hybrid = {
            "zyntry_managed",
            "end_user_oauth",
        }.issubset(defn.connection_modes)
        if (is_hybrid and not supports_hybrid) or (
            not is_hybrid and data.connection_mode not in defn.connection_modes
        ):
            raise ValueError(
                f"Connection mode '{data.connection_mode}' is not supported for '{data.integration_slug}'. "
                f"Supported modes: {defn.connection_modes}"
            )

        # Validate requested capabilities
        all_caps = {c.slug for c in defn.capabilities}
        enabled_caps = data.enabled_capabilities or [c.slug for c in defn.capabilities if not c.is_write]
        invalid_caps = set(enabled_caps) - all_caps
        if invalid_caps:
            raise ValueError(f"Invalid capabilities for {data.integration_slug}: {invalid_caps}")

        connection_required = data.connection_mode in {"zyntry_managed", "hybrid"}
        connection_status = (
            "connection_required" if connection_required else "ready_for_end_users"
        )
        policy_config = {
            **data.config,
            "allowed_connection_modes": (
                ["zyntry_managed", "end_user_oauth"]
                if data.connection_mode == "hybrid"
                else [data.connection_mode]
            ),
        }

        existing = await self.uow.runtime_integrations.get_by_runtime_and_slug(
            rid, data.integration_slug
        )
        if existing:
            updated = await self.uow.runtime_integrations.update(
                existing,
                connection_mode=data.connection_mode,
                enabled_capabilities=enabled_caps,
                is_enabled=True,
                connection_required=connection_required,
                connection_status=connection_status,
                config=policy_config,
            )
            await self.uow.commit()
            return updated

        created = await self.uow.runtime_integrations.create(
            runtime_id=rid,
            integration_slug=data.integration_slug,
            connection_mode=data.connection_mode,
            enabled_capabilities=enabled_caps,
            is_enabled=True,
            connection_required=connection_required,
            connection_status=connection_status,
            config=policy_config,
        )
        await self.uow.commit()
        return created

    async def update_runtime_integration(
        self, runtime_id: str | UUID, integration_slug: str, data: RuntimeIntegrationUpdate
    ) -> RuntimeIntegration:
        rid = UUID(str(runtime_id)) if isinstance(runtime_id, str) else runtime_id
        existing = await self.uow.runtime_integrations.get_by_runtime_and_slug(
            rid, integration_slug
        )
        if not existing:
            raise ValueError(f"Integration '{integration_slug}' is not configured on this runtime")

        kwargs: dict[str, Any] = {}
        if data.enabled_capabilities is not None:
            defn = integration_registry.get(integration_slug)
            if defn:
                all_caps = {c.slug for c in defn.capabilities}
                invalid_caps = set(data.enabled_capabilities) - all_caps
                if invalid_caps:
                    raise ValueError(f"Invalid capabilities for {integration_slug}: {invalid_caps}")
            kwargs["enabled_capabilities"] = data.enabled_capabilities

        if data.is_enabled is not None:
            kwargs["is_enabled"] = data.is_enabled
        if data.config is not None:
            kwargs["config"] = data.config

        updated = await self.uow.runtime_integrations.update(existing, **kwargs)
        await self.uow.commit()
        return updated

    async def disable_runtime_integration(
        self, runtime_id: str | UUID, integration_slug: str
    ) -> None:
        rid = UUID(str(runtime_id)) if isinstance(runtime_id, str) else runtime_id
        existing = await self.uow.runtime_integrations.get_by_runtime_and_slug(
            rid, integration_slug
        )
        if existing:
            await self.uow.runtime_integrations.delete(existing)
            await self.uow.commit()

    async def is_capability_enabled(
        self, runtime_id: str | UUID, integration_slug: str, capability: str
    ) -> bool:
        rid = UUID(str(runtime_id)) if isinstance(runtime_id, str) else runtime_id
        item = await self.uow.runtime_integrations.get_by_runtime_and_slug(rid, integration_slug)
        if not item or not item.is_enabled:
            return False
        return capability in item.enabled_capabilities

    # Legacy helper for OAuth backward compatibility
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
            "project_id": project_id,
            "purpose": purpose,
            "oauth_connection_id": oauth_connection_id,
            "tool_id": tool_id,
            "source_id": source_id,
        }
