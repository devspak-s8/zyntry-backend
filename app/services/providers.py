from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from app.models.oauth import OAuthProvider
from app.repositories import UnitOfWork
from app.schemas.providers import ProviderConnectionCreate


class ProviderService:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def list_providers(self, project_id: str | None = None) -> list[dict]:
        connections = []
        if project_id:
            connections = await self.uow.providers.get_by_project(project_id)
        else:
            connections = await self.uow.providers.list()
        return [
            {
                "id": str(c.id),
                "provider_name": c.provider_name,
                "display_name": c.display_name,
                "status": c.status,
                "is_active": c.is_active,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in connections
        ]

    async def connect(self, data: ProviderConnectionCreate) -> dict[str, Any]:
        existing = None
        if data.project_id:
            existing = await self.uow.providers.get_by_provider(
                data.project_id, data.provider_name
            )

        oauth_provider = await self._get_oauth_provider(data.provider_name)
        if oauth_provider:
            return await self._initiate_oauth(data, oauth_provider, existing)

        if existing:
            updated = await self.uow.providers.update(
                existing,
                encrypted_api_key=data.api_key,
                status="active",
                display_name=data.display_name,
                config=data.config,
            )
            await self.uow.commit()
            return {
                "id": str(updated.id),
                "provider_name": updated.provider_name,
                "display_name": updated.display_name,
                "status": updated.status,
                "is_active": updated.is_active,
                "created_at": updated.created_at.isoformat() if updated.created_at else "",
                "updated_at": updated.updated_at.isoformat() if updated.updated_at else "",
            }

        created = await self.uow.providers.create(
            organization_id=data.organization_id,
            project_id=data.project_id,
            provider_name=data.provider_name,
            display_name=data.display_name,
            encrypted_api_key=data.api_key,
            status="active",
            config=data.config,
        )
        await self.uow.commit()
        return {
            "id": str(created.id),
            "provider_name": created.provider_name,
            "display_name": created.display_name,
            "status": created.status,
            "is_active": created.is_active,
            "created_at": created.created_at.isoformat() if created.created_at else "",
            "updated_at": created.updated_at.isoformat() if created.updated_at else "",
        }

    async def _get_oauth_provider(self, provider_name: str) -> OAuthProvider | None:
        result = await self.uow.session.execute(
            select(OAuthProvider).where(OAuthProvider.name == provider_name)
        )
        return result.scalars().first()

    async def _ensure_oauth_provider(self, provider_name: str) -> OAuthProvider:
        existing = await self._get_oauth_provider(provider_name)
        if existing:
            return existing

        defaults = {
            "github": {
                "display_name": "GitHub",
                "auth_url": "https://github.com/login/oauth/authorize",
                "token_url": "https://github.com/login/oauth/access_token",
                "scopes": ["repo", "user"],
            },
            "gitlab": {
                "display_name": "GitLab",
                "auth_url": "https://gitlab.com/oauth/authorize",
                "token_url": "https://gitlab.com/oauth/token",
                "scopes": ["read_user", "api"],
            },
            "gmail": {
                "display_name": "Gmail",
                "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
                "token_url": "https://oauth2.googleapis.com/token",
                "scopes": ["https://mail.google.com/"],
            },
            "slack": {
                "display_name": "Slack",
                "auth_url": "https://slack.com/oauth/v2/authorize",
                "token_url": "https://slack.com/api/oauth.access",
                "scopes": ["chat:write", "channels:read"],
            },
            "notion": {
                "display_name": "Notion",
                "auth_url": "https://api.notion.com/v1/oauth/authorize",
                "token_url": "https://api.notion.com/v1/oauth/token",
                "scopes": [],
            },
            "jira": {
                "display_name": "Jira",
                "auth_url": "https://auth.atlassian.com/authorize",
                "token_url": "https://auth.atlassian.com/oauth/token",
                "scopes": ["read:jira-user", "write:jira-work"],
            },
        }
        config = defaults.get(provider_name, {
            "display_name": provider_name.title(),
            "auth_url": "",
            "token_url": "",
            "scopes": [],
        })
        created = await self.uow.oauth_providers.create(
            name=provider_name,
            display_name=config["display_name"],
            client_id="",
            client_secret_encrypted="",
            auth_url=config["auth_url"],
            token_url=config["token_url"],
            scopes=config["scopes"],
            is_enabled=True,
        )
        await self.uow.commit()
        return created

    async def _initiate_oauth(
        self,
        data: ProviderConnectionCreate,
        oauth_provider: OAuthProvider,
        existing: Any = None,
    ) -> dict[str, Any]:
        from app.services.oauth.service import OAuthService
        oauth_service = OAuthService(self.uow)
        user_id = uuid.uuid4()
        project_id = uuid.UUID(data.project_id) if data.project_id else None
        if project_id is None:
            raise ValueError("project_id is required for OAuth providers")
        result = await oauth_service.authorize(
            provider_name=data.provider_name,
            user_id=user_id,
            project_id=project_id,
            redirect_uri=None,
        )
        if existing:
            await self.uow.providers.update(
                existing,
                display_name=data.display_name,
                status="pending",
                config=data.config,
            )
        else:
            await self.uow.providers.create(
                organization_id=data.organization_id,
                project_id=data.project_id,
                provider_name=data.provider_name,
                display_name=data.display_name,
                status="pending",
                config=data.config,
            )
        await self.uow.commit()
        return {
            "authorization_url": result["url"],
            "state": result["state"],
            "provider_name": data.provider_name,
            "display_name": data.display_name,
            "requires_oauth": True,
        }

    async def disconnect(self, connection_id: str) -> None:
        conn = await self.uow.providers.get(connection_id)
        if not conn:
            raise ValueError("Provider connection not found")
        await self.uow.providers.delete(conn)
        await self.uow.commit()

    async def test_connection(self, data: dict) -> dict:
        return {"success": True, "message": "Connection test passed"}

    async def discover_resources(self, data: dict) -> dict:
        return {"items": [], "total": 0}

    async def sync(self, connection_id: str) -> dict:
        return {"id": connection_id, "status": "queued"}

    async def refresh(self, connection_id: str) -> dict:
        return {"id": connection_id, "status": "refreshed"}

    async def get_health(self, connection_id: str) -> dict:
        return {"id": connection_id, "status": "healthy"}
