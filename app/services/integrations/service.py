from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from app.models.integrations import RuntimeIntegration
from app.repositories import UnitOfWork
from app.schemas.integrations import (
    IntegrationDefinitionRead,
    RuntimeIntegrationCreate,
    RuntimeIntegrationUpdate,
)
from app.services.integrations.definitions import integration_registry
from app.services.tools import ToolService

ConnectionPurpose = Literal["source", "tool", "both"]
SOURCE_CONNECTORS = {
    "github",
    "notion",
    "slack",
    "google_drive",
    "google_people",
    "google_sheets",
    "google_docs",
    "google_chat",
    "google_meet",
    "google_forms",
}


class IntegrationService:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    @staticmethod
    def _resolve_connection_mode(
        integration_slug: str,
        requested_mode: str | None,
    ) -> tuple[str | None, str]:
        """Resolve a requested mode against the canonical registry definition."""
        if not requested_mode:
            return None, "not_selected"
        definition = integration_registry.get(integration_slug)
        if definition is None:
            return requested_mode, "requested"
        supports_hybrid = {
            "zyntry_managed",
            "end_user_oauth",
        }.issubset(definition.connection_modes)
        if requested_mode == "hybrid" and not supports_hybrid:
            return "zyntry_managed", "company_managed_only"
        if requested_mode not in definition.connection_modes and requested_mode != "hybrid":
            raise ValueError(
                f"Connection mode '{requested_mode}' is not supported for "
                f"'{definition.slug}'. Supported modes: {definition.connection_modes}"
            )
        return requested_mode, "requested"

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
        items = await self.uow.runtime_integrations.get_by_runtime(rid)
        changed = False
        for item in items:
            defn = integration_registry.get(item.integration_slug)
            supports_hybrid = defn is not None and {
                "zyntry_managed",
                "end_user_oauth",
            }.issubset(defn.connection_modes)
            if item.connection_mode == "hybrid" and not supports_hybrid:
                item.connection_mode = "zyntry_managed"
                item.connection_required = True
                if item.connection_status == "ready_for_end_users":
                    item.connection_status = "connection_required"
                item.config = {
                    **(item.config or {}),
                    "requested_connection_mode": "hybrid",
                    "mode_resolution": "company_managed_only",
                    "allowed_connection_modes": ["zyntry_managed"],
                }
                changed = True
        if changed:
            await self.uow.commit()
        return items

    async def reconcile_runtime_policies(
        self,
        runtime_id: str | UUID,
        policies: list[dict[str, Any]] | None,
        *,
        canonicalize_slugs: bool = True,
    ) -> list[RuntimeIntegration]:
        """Materialize the policies saved on a runtime into integration rows.

        Runtime creation historically persisted onboarding policies inside the
        runtime config, while the integrations API reads the separate
        ``runtime_integrations`` table.  Rebinding an existing runtime must
        reconcile that boundary or the project will appear to have no
        integrations at all.  This method intentionally does not commit so a
        project bind and its policy materialization remain one transaction.
        """
        rid = UUID(str(runtime_id)) if isinstance(runtime_id, str) else runtime_id
        runtime = await self.uow.runtimes.get(rid)
        if runtime is None:
            raise ValueError(f"Runtime '{runtime_id}' not found")

        resource_only_slugs = {
            "pdf",
            "docx",
            "txt",
            "csv",
            "markdown",
            "html",
            "json",
            "document_storage",
        }
        materialized: list[RuntimeIntegration] = []
        runtime_config = runtime.config or {}
        default_mode = runtime_config.get("integration_mode") or "zyntry_managed"

        for raw_policy in policies or []:
            if not isinstance(raw_policy, dict):
                continue
            requested_slug = raw_policy.get("integration_slug") or raw_policy.get("slug")
            if not isinstance(requested_slug, str) or not requested_slug.strip():
                continue
            definition = integration_registry.get(requested_slug.strip())
            if (
                definition is None
                or not definition.enabled
                or definition.status not in ("available", "beta")
                or definition.slug in resource_only_slugs
            ):
                # Documents and file formats are project resources, not rows
                # in the connector table. Unsupported services must never be
                # materialized as if they were connected.
                continue
            storage_slug = definition.slug if canonicalize_slugs else requested_slug.strip().lower()

            requested_mode = (
                raw_policy.get("requested_connection_mode")
                or raw_policy.get("connection_mode")
                or default_mode
            )
            if not isinstance(requested_mode, str) or not requested_mode.strip():
                requested_mode = "zyntry_managed"
            effective_mode, mode_resolution = self._resolve_connection_mode(
                definition.slug, requested_mode
            )
            effective_mode = effective_mode or "zyntry_managed"

            all_capabilities = {cap.slug for cap in definition.capabilities}
            requested_capabilities = raw_policy.get("enabled_capabilities")
            enabled_capabilities = (
                list(dict.fromkeys(requested_capabilities))
                if isinstance(requested_capabilities, list) and requested_capabilities
                else [cap.slug for cap in definition.capabilities if not cap.is_write]
            )
            invalid_capabilities = set(enabled_capabilities) - all_capabilities
            if invalid_capabilities:
                # A stale plan should not prevent project creation. Keep only
                # capabilities that still exist in the current registry.
                enabled_capabilities = [
                    capability
                    for capability in enabled_capabilities
                    if capability in all_capabilities
                ]

            existing = await self.uow.runtime_integrations.get_by_runtime_and_slug(
                rid, storage_slug
            )
            linked_connection = None
            if existing and existing.connection_id:
                linked_connection = await self.uow.integration_connections.get(
                    existing.connection_id
                )
            connection_is_valid = bool(
                linked_connection
                and linked_connection.status == "active"
                and linked_connection.integration_slug == storage_slug
                and linked_connection.connection_mode == effective_mode
            )
            connection_required = effective_mode in {"zyntry_managed", "hybrid"}
            raw_config = raw_policy.get("config")
            base_config: dict[str, Any] = raw_config if isinstance(raw_config, dict) else {}
            policy_config = {
                **base_config,
                "allowed_connection_modes": (
                    ["zyntry_managed", "end_user_oauth"]
                    if effective_mode == "hybrid"
                    else [effective_mode]
                ),
                "requested_connection_mode": requested_mode,
                "mode_resolution": mode_resolution,
            }
            values = {
                "connection_mode": effective_mode,
                "enabled_capabilities": enabled_capabilities,
                "is_enabled": True,
                "connection_id": (
                    linked_connection.id if connection_is_valid and linked_connection else None
                ),
                "connection_required": False if connection_is_valid else connection_required,
                "connection_status": "connected"
                if connection_is_valid
                else ("ready_for_end_users" if effective_mode == "end_user_oauth" else "connection_required"),
                "config": policy_config,
            }
            if existing:
                item = await self.uow.runtime_integrations.update(existing, **values)
            else:
                item = await self.uow.runtime_integrations.create(
                    runtime_id=rid,
                    integration_slug=storage_slug,
                    **values,
                )
            materialized.append(item)

        return materialized

    async def enable_runtime_integration(
        self,
        runtime_id: str | UUID,
        data: RuntimeIntegrationCreate,
        user_id: UUID | None = None,
    ) -> RuntimeIntegration:
        rid = UUID(str(runtime_id)) if isinstance(runtime_id, str) else runtime_id
        runtime = await self.uow.runtimes.get(rid)
        if runtime is None:
            raise ValueError(f"Runtime '{runtime_id}' not found")
        if user_id and runtime.user_id != user_id:
            raise PermissionError("Unauthorized to modify this runtime")

        # Keep the explicit connector API strict. Runtime-policy reconciliation
        # uses the same registry rules but can safely drop stale capabilities.
        defn = integration_registry.get(data.integration_slug)
        if defn is None:
            raise ValueError(f"Integration '{data.integration_slug}' is not supported")
        if defn.status not in ("available", "beta"):
            raise ValueError(
                f"Integration '{data.integration_slug}' is currently '{defn.status}' and cannot be enabled on active runtimes"
            )
        enabled_caps = data.enabled_capabilities or [c.slug for c in defn.capabilities if not c.is_write]
        invalid_caps = set(enabled_caps) - {c.slug for c in defn.capabilities}
        if invalid_caps:
            raise ValueError(f"Invalid capabilities for {data.integration_slug}: {invalid_caps}")

        requested_mode = data.connection_mode
        effective_mode, mode_resolution = self._resolve_connection_mode(
            defn.slug, requested_mode
        )
        if effective_mode is None:
            effective_mode = "zyntry_managed"
        policy = {
            "integration_slug": data.integration_slug,
            "requested_connection_mode": requested_mode,
            "connection_mode": effective_mode,
            "enabled_capabilities": enabled_caps,
            "config": data.config,
        }
        # Preserve the strict validation above, then use one reconciliation
        # path so explicit enables and project rebinding cannot diverge.
        created_or_updated = await self.reconcile_runtime_policies(
            rid,
            [policy],
            canonicalize_slugs=False,
        )
        if not created_or_updated:
            raise ValueError(f"Integration '{data.integration_slug}' is not supported")
        created = created_or_updated[0]
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
        if data.connection_mode is not None:
            definition = integration_registry.get(existing.integration_slug)
            if definition is None:
                raise ValueError(f"Integration '{integration_slug}' is not supported")

            next_mode, mode_resolution = self._resolve_connection_mode(
                existing.integration_slug,
                data.connection_mode,
            )
            next_mode = next_mode or "zyntry_managed"
            if next_mode != existing.connection_mode:
                current_config = dict(existing.config or {})
                previous_mode = current_config.get("previous_connection_mode")
                previous_connection_id = current_config.get("previous_connection_id")
                restored_connection = None
                if previous_mode == next_mode and previous_connection_id:
                    try:
                        restored_connection = await self.uow.integration_connections.get(
                            UUID(str(previous_connection_id))
                        )
                    except (TypeError, ValueError):
                        restored_connection = None
                    if (
                        restored_connection is None
                        or restored_connection.status != "active"
                        or restored_connection.connection_mode != next_mode
                    ):
                        restored_connection = None

                if restored_connection is not None:
                    next_config = {
                        **current_config,
                        "mode_change": {
                            "from": existing.connection_mode,
                            "to": next_mode,
                            "status": "restored",
                        },
                    }
                    kwargs.update(
                        connection_mode=next_mode,
                        connection_id=restored_connection.id,
                        connection_required=False,
                        connection_status="connected",
                        config=next_config,
                    )
                else:
                    old_connection_id = str(existing.connection_id) if existing.connection_id else None
                    next_config = {
                        **current_config,
                        "allowed_connection_modes": (
                            ["zyntry_managed", "end_user_oauth"]
                            if next_mode == "hybrid"
                            else [next_mode]
                        ),
                        "requested_connection_mode": data.connection_mode,
                        "mode_resolution": mode_resolution,
                        "previous_connection_mode": existing.connection_mode,
                        "previous_connection_id": old_connection_id,
                        "mode_change": {
                            "from": existing.connection_mode,
                            "to": next_mode,
                            "status": "pending_connection",
                        },
                    }
                    kwargs.update(
                        connection_mode=next_mode,
                        # Keep the old connection row intact for rollback, but
                        # do not use it while the new mode is being prepared.
                        connection_id=None,
                        connection_required=next_mode in {"zyntry_managed", "hybrid"},
                        connection_status=(
                            "ready_for_end_users"
                            if next_mode == "end_user_oauth"
                            else "connection_required"
                        ),
                        config=next_config,
                    )

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
            sources = await self.uow.knowledge_sources.get_by_project(UUID(project_id))
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
