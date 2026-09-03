from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from app.core.config import settings
from app.models.integrations import IntegrationConnection
from app.models.oauth import OAuthState
from app.repositories import UnitOfWork
from app.schemas.integrations import ConnectionAuthorizeRequest, ConnectionAuthorizeResponse, ConnectionDirectCreate
from app.services.integrations.auth_providers import default_github_provider, default_oauth_provider
from app.services.integrations.definitions import integration_registry
from app.services.security.secrets import SecretManager, default_secret_manager

logger = logging.getLogger(__name__)


class ConnectionService:
    def __init__(self, uow: UnitOfWork, secret_manager: SecretManager | None = None) -> None:
        self.uow = uow
        self.secrets = secret_manager or default_secret_manager

    async def authorize(
        self,
        integration_slug: str,
        user_id: UUID | None,
        data: ConnectionAuthorizeRequest,
    ) -> ConnectionAuthorizeResponse:
        defn = integration_registry.get(integration_slug)
        if defn is None:
            raise ValueError(f"Integration '{integration_slug}' is not supported")

        # Only integrations explicitly configured for OAuth may enter this
        # flow. File-upload and other managed capabilities (for example
        # ``document_storage``) must be handled by their own endpoints.
        if "oauth2" not in defn.auth_methods:
            raise ValueError(
                f"Integration '{integration_slug}' does not support OAuth authorization"
            )

        if data.connection_mode not in defn.supported_connection_modes:
            raise ValueError(
                f"Connection mode '{data.connection_mode}' is not supported for '{integration_slug}'"
            )

        # Mode B check: end_user_id is recommended for end_user_oauth
        runtime_uuid = UUID(data.runtime_id) if data.runtime_id else None

        # Verify runtime has integration capability enabled if runtime_id is provided
        if runtime_uuid:
            runtime_int = await self.uow.runtime_integrations.get_by_runtime_and_slug(
                runtime_uuid, integration_slug
            )
            if runtime_int is None or not runtime_int.is_enabled:
                raise ValueError(
                    f"Integration capability '{integration_slug}' is not enabled on runtime {data.runtime_id}"
                )

        # Check existing active connection
        if data.connection_mode == "zyntry_managed" and user_id:
            existing = await self.uow.integration_connections.get_zyntry_managed(
                user_id, integration_slug
            )
            if existing and existing.status == "active":
                return ConnectionAuthorizeResponse(
                    requires_authorization=False,
                    integration_slug=integration_slug,
                    connection_mode="zyntry_managed",
                    connection_id=str(existing.id),
                )
        elif data.connection_mode == "end_user_oauth" and runtime_uuid and data.end_user_id:
            existing = await self.uow.integration_connections.get_for_end_user(
                runtime_uuid, integration_slug, data.end_user_id
            )
            if existing and existing.status == "active":
                return ConnectionAuthorizeResponse(
                    requires_authorization=False,
                    integration_slug=integration_slug,
                    connection_mode="end_user_oauth",
                    connection_id=str(existing.id),
                )

        redirect_uri = (
            data.redirect_uri
            or f"{settings.APP_URL.rstrip('/')}/api/v1/connections/{integration_slug}/callback"
        )

        auth_provider = default_github_provider if integration_slug == "github" else default_oauth_provider
        flow = auth_provider.generate_auth_flow(
            integration=defn,
            redirect_uri=redirect_uri,
            scope_override=data.scopes,
        )

        # Persist state with cryptographic expiration
        expires_at = datetime.now(UTC) + timedelta(minutes=10)
        await self.uow.oauth_states.create(
            provider=integration_slug,
            state=flow["state"],
            code_verifier=flow["code_verifier"],
            user_id=user_id,
            project_id=None,
            redirect_uri=redirect_uri,
            purpose=data.connection_mode,
            display_name=data.display_name or f"{defn.name} Connection",
            source_config={
                "runtime_id": str(runtime_uuid) if runtime_uuid else None,
                "end_user_id": data.end_user_id,
                "connection_mode": data.connection_mode,
                "custom_config": data.config,
            },
            expires_at=expires_at,
        )
        await self.uow.commit()

        return ConnectionAuthorizeResponse(
            requires_authorization=True,
            url=flow["url"],
            state=flow["state"],
            integration_slug=integration_slug,
            connection_mode=data.connection_mode,
        )

    async def handle_callback(
        self,
        integration_slug: str,
        code: str,
        state: str,
        expected_user_id: UUID | None = None,
    ) -> IntegrationConnection:
        state_obj: OAuthState | None = await self.uow.oauth_states.get_by_state(state)
        if state_obj is None:
            raise ValueError("Invalid or expired OAuth state")

        now = datetime.now(UTC)
        exp = state_obj.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=UTC)
        if exp <= now:
            raise ValueError("OAuth state has expired")

        if expected_user_id and state_obj.user_id and state_obj.user_id != expected_user_id:
            raise ValueError("OAuth state does not belong to the current authenticated user")

        defn = integration_registry.get(integration_slug)
        if defn is None:
            raise ValueError(f"Unknown integration: {integration_slug}")

        auth_provider = default_github_provider if integration_slug == "github" else default_oauth_provider
        token_data = await auth_provider.exchange_code(
            integration=defn,
            code=code,
            redirect_uri=state_obj.redirect_uri or f"{settings.APP_URL.rstrip('/')}/api/v1/connections/{integration_slug}/callback",
            code_verifier=state_obj.code_verifier,
        )

        source_config = dict(state_obj.source_config or {})
        runtime_id_str = source_config.get("runtime_id")
        runtime_id = UUID(runtime_id_str) if runtime_id_str else None
        end_user_id = source_config.get("end_user_id")
        connection_mode = state_obj.purpose or source_config.get("connection_mode") or "zyntry_managed"

        if runtime_id:
            runtime = await self.uow.runtimes.get(runtime_id)
            owner = await self.uow.users.get(state_obj.user_id) if state_obj.user_id else None
            if runtime is None or owner is None:
                raise ValueError("OAuth runtime is no longer available")
            if runtime.project_id:
                project = await self.uow.projects.get(runtime.project_id)
                if project is None or project.organization_id != owner.organization_id:
                    raise ValueError("OAuth runtime is not authorized for this user")
            elif runtime.user_id != owner.id:
                raise ValueError("OAuth runtime is not authorized for this user")

        # Encrypt token payload inside structured envelope
        secret_payload = json.dumps({
            "access_token": token_data.get("access_token"),
            "token_type": token_data.get("token_type", "Bearer"),
        })
        encrypted_creds = self.secrets.encrypt(secret_payload)

        scopes = token_data.get("scope", "").split() if token_data.get("scope") else defn.required_scopes
        expires_in = token_data.get("expires_in")
        expires_at = datetime.now(UTC) + timedelta(seconds=expires_in) if expires_in else None

        refresh_meta = {}
        if token_data.get("refresh_token"):
            refresh_meta["encrypted_refresh_token"] = self.secrets.encrypt(token_data["refresh_token"])

        # Create or update connection
        connection = await self.uow.integration_connections.create(
            user_id=state_obj.user_id,
            runtime_id=runtime_id,
            integration_slug=integration_slug,
            connection_mode=connection_mode,
            end_user_id=end_user_id,
            display_name=state_obj.display_name or f"{defn.name} ({connection_mode})",
            auth_method="oauth2",
            encrypted_credentials=encrypted_creds,
            scopes=scopes,
            expires_at=expires_at,
            refresh_metadata=refresh_meta,
            last_synchronized_at=datetime.now(UTC),
            status="active",
            health_status="healthy",
            metadata_={"connected_at": datetime.now(UTC).isoformat()},
        )

        # If connected to a runtime for Mode A, link the connection_id
        if runtime_id and connection_mode == "zyntry_managed":
            runtime_int = await self.uow.runtime_integrations.get_by_runtime_and_slug(
                runtime_id, integration_slug
            )
            if runtime_int:
                await self.uow.runtime_integrations.update(
                    runtime_int,
                    connection_id=connection.id,
                    connection_status="connected",
                )

        await self.uow.commit()
        return connection

    async def create_direct_connection(
        self,
        user_id: UUID | None,
        data: ConnectionDirectCreate,
    ) -> IntegrationConnection:
        defn = integration_registry.get(data.integration_slug)
        if defn is None:
            raise ValueError(f"Unknown integration: {data.integration_slug}")

        runtime_uuid = UUID(data.runtime_id) if data.runtime_id else None

        requested_slug = data.integration_slug
        canonical_slug = defn.slug

        # Verify capability enabled on runtime if runtime_id specified
        if runtime_uuid:
            runtime_int = await self.uow.runtime_integrations.get_by_runtime_and_slug(
                runtime_uuid, requested_slug
            )
            if runtime_int is None and canonical_slug != requested_slug:
                runtime_int = await self.uow.runtime_integrations.get_by_runtime_and_slug(
                    runtime_uuid, canonical_slug
                )
            if runtime_int is None or not runtime_int.is_enabled:
                raise ValueError(
                    f"Integration capability '{requested_slug}' is not enabled on runtime {data.runtime_id}"
                )

        # Keep an explicitly enabled legacy alias on the connection; otherwise
        # use the registry's canonical slug for new standalone connections.
        data.integration_slug = runtime_int.integration_slug if runtime_uuid and runtime_int else canonical_slug

        secret_payload = json.dumps(data.credentials)
        encrypted_creds = self.secrets.encrypt(secret_payload)

        connection = await self.uow.integration_connections.create(
            user_id=user_id,
            runtime_id=runtime_uuid,
            integration_slug=data.integration_slug,
            connection_mode=data.connection_mode,
            end_user_id=data.end_user_id,
            display_name=data.display_name,
            auth_method=data.auth_method,
            encrypted_credentials=encrypted_creds,
            scopes=defn.required_scopes,
            last_synchronized_at=datetime.now(UTC),
            status="active",
            health_status="healthy",
            metadata_=data.metadata,
        )

        if runtime_uuid and data.connection_mode == "zyntry_managed":
            runtime_int = await self.uow.runtime_integrations.get_by_runtime_and_slug(
                runtime_uuid, data.integration_slug
            )
            if runtime_int:
                await self.uow.runtime_integrations.update(
                    runtime_int,
                    connection_id=connection.id,
                    connection_status="connected",
                )

        await self.uow.commit()
        return connection

    async def get_connection_for_execution(
        self,
        runtime_id: UUID,
        integration_slug: str,
        end_user_id: str | None = None,
    ) -> dict[str, Any]:
        """Authorize and retrieve decrypted credentials for tool/action execution with isolation."""
        runtime_int = await self.uow.runtime_integrations.get_by_runtime_and_slug(
            runtime_id, integration_slug
        )
        if runtime_int is None or not runtime_int.is_enabled:
            raise PermissionError(
                f"Capability '{integration_slug}' is not enabled for runtime {runtime_id}"
            )

        connection: IntegrationConnection | None = None

        if runtime_int.connection_mode == "end_user_oauth":
            if not end_user_id:
                raise ValueError(
                    f"Integration '{integration_slug}' is in BYO-user mode; end_user_id is required"
                )
            connection = await self.uow.integration_connections.get_for_end_user(
                runtime_id, integration_slug, end_user_id
            )
        else:
            if runtime_int.connection_id:
                connection = await self.uow.integration_connections.get(runtime_int.connection_id)
            if not connection:
                runtime = await self.uow.runtimes.get(runtime_id)
                if runtime and runtime.user_id:
                    connection = await self.uow.integration_connections.get_zyntry_managed(
                        runtime.user_id, integration_slug
                    )

        if connection is None or connection.status != "active":
            raise PermissionError(
                f"No active authorized connection found for '{integration_slug}' on runtime {runtime_id}"
            )

        if connection.expires_at and connection.expires_at <= datetime.now(UTC):
            raise PermissionError(
                f"Connection for '{integration_slug}' has expired. Re-authorization required."
            )

        defn = integration_registry.get(integration_slug)
        if defn is not None:
            required_scopes: set[str] = set()
            capability_map = {cap.slug: cap for cap in defn.capabilities}
            for capability in runtime_int.enabled_capabilities or []:
                definition = capability_map.get(capability)
                if definition is not None:
                    required_scopes.update(definition.required_scopes)
            # Some integrations put their read scope on the top-level
            # definition rather than each capability.  Enforce it whenever a
            # capability has no narrower declaration.
            if not required_scopes:
                required_scopes.update(defn.required_scopes)
            granted_scopes = {
                str(scope).strip()
                for scope in (connection.scopes or [])
                if str(scope).strip()
            }
            missing_scopes = sorted(
                required
                for required in required_scopes
                if not any(
                    granted == required
                    or granted.endswith(f"/{required}")
                    or granted.endswith(f":{required}")
                    for granted in granted_scopes
                )
            )
            if missing_scopes:
                raise PermissionError(
                    f"Connection for '{integration_slug}' is missing required API scopes: "
                    f"{', '.join(missing_scopes)}"
                )

        # Decrypt credentials
        raw_creds = {}
        if connection.encrypted_credentials:
            decrypted_str = self.secrets.decrypt(connection.encrypted_credentials)
            raw_creds = json.loads(decrypted_str)

        return {
            "connection_id": str(connection.id),
            "integration_slug": integration_slug,
            "connection_mode": connection.connection_mode,
            "auth_method": connection.auth_method,
            "scopes": connection.scopes,
            "credentials": raw_creds,
            "enabled_capabilities": runtime_int.enabled_capabilities,
        }

    async def list_connections(
        self,
        user_id: UUID | None = None,
        runtime_id: str | None = None,
        integration_slug: str | None = None,
        end_user_id: str | None = None,
        connection_mode: str | None = None,
    ) -> list[IntegrationConnection]:
        rid = UUID(runtime_id) if runtime_id else None
        return await self.uow.integration_connections.list_connections(
            user_id=user_id,
            runtime_id=rid,
            integration_slug=integration_slug,
            end_user_id=end_user_id,
            connection_mode=connection_mode,
        )

    async def get_connection(self, connection_id: UUID) -> IntegrationConnection | None:
        return await self.uow.integration_connections.get(connection_id)

    async def revoke_connection(self, connection_id: UUID) -> None:
        conn = await self.uow.integration_connections.get(connection_id)
        if not conn:
            raise ValueError("Connection not found")
        await self.uow.integration_connections.update(
            conn,
            status="revoked",
            encrypted_credentials=None,
        )
        await self.uow.commit()
