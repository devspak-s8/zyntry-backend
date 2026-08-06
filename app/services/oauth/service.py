from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select

from app.core.config import settings
from app.models.oauth import OAuthConnection, OAuthProvider, OAuthState
from app.repositories import UnitOfWork


class OAuthError(Exception):
    pass


class OAuthService:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def list_providers(self) -> list[dict[str, Any]]:
        providers = await self.uow.session.execute(
            select(OAuthProvider).where(OAuthProvider.is_enabled)
        )
        rows = providers.scalars().all()
        return [
            {
                "id": str(p.id),
                "name": p.name,
                "display_name": p.display_name,
                "scopes": p.scopes,
                "is_enabled": p.is_enabled,
            }
            for p in rows
        ]

    async def get_provider(self, name: str) -> OAuthProvider | None:
        result = await self.uow.session.execute(
            select(OAuthProvider).where(OAuthProvider.name == name)
        )
        return result.scalars().first()

    async def authorize(
        self,
        provider_name: str,
        user_id: uuid.UUID,
        project_id: uuid.UUID | None = None,
        redirect_uri: str | None = None,
    ) -> dict[str, Any]:
        provider = await self.get_provider(provider_name)
        if provider is None:
            raise OAuthError(f"Provider '{provider_name}' not found")

        state = secrets.token_urlsafe(32)
        code_verifier = secrets.token_urlsafe(64)
        expires_at = datetime.now(UTC) + timedelta(minutes=10)

        await self.uow.oauth_states.create(
            provider=provider_name,
            state=state,
            code_verifier=code_verifier,
            user_id=user_id,
            project_id=project_id,
            redirect_uri=redirect_uri,
            expires_at=expires_at,
        )
        await self.uow.commit()

        params = {
            "client_id": provider.client_id,
            "redirect_uri": redirect_uri or f"{settings.APP_URL}/api/v1/oauth/callback",
            "response_type": "code",
            "scope": " ".join(provider.scopes),
            "state": state,
            "code_challenge": self._generate_code_challenge(code_verifier),
            "code_challenge_method": "S256",
        }
        url = f"{provider.auth_url}?{'&'.join(f'{k}={v}' for k, v in params.items())}"
        return {"url": url, "state": state}

    async def callback(
        self,
        provider_name: str,
        code: str,
        state: str,
        project_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        state_obj = await self._validate_state(provider_name, state)
        provider = await self.get_provider(provider_name)
        if provider is None:
            raise OAuthError(f"Provider '{provider_name}' not found")

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                provider.token_url,
                data={
                    "grant_type": "authorization_code",
                    "client_id": provider.client_id,
                    "client_secret": self._decrypt(provider.client_secret_encrypted),
                    "code": code,
                    "redirect_uri": (
                        state_obj.redirect_uri
                        or f"{settings.APP_URL}/api/v1/oauth/callback"
                    ),
                    "code_verifier": state_obj.code_verifier,
                },
            )
            if resp.status_code != 200:
                raise OAuthError(f"Token exchange failed: {resp.status_code} {resp.text}")
            token_data = resp.json()

        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in")
        scope = token_data.get("scope")

        if not access_token:
            raise OAuthError("No access token in response")

        expires_at = None
        if expires_in:
            expires_at = datetime.now(UTC) + timedelta(seconds=int(expires_in))

        user_info = await self._fetch_user_info(provider_name, access_token)
        connection = OAuthConnection(
            user_id=state_obj.user_id,
            project_id=project_id or state_obj.project_id,
            provider_id=provider.id,
            access_token_encrypted=self._encrypt(access_token),
            refresh_token_encrypted=self._encrypt(refresh_token) if refresh_token else None,
            expires_at=expires_at,
            scope=scope,
            metadata_={"user_info": user_info},
        )
        await self.uow.oauth_connections.create(
            user_id=state_obj.user_id,
            project_id=project_id or state_obj.project_id,
            provider_id=provider.id,
            access_token_encrypted=self._encrypt(access_token),
            refresh_token_encrypted=self._encrypt(refresh_token) if refresh_token else None,
            expires_at=expires_at,
            scope=scope,
        )
        await self.uow.commit()

        await self.uow.session.delete(state_obj)
        await self.uow.commit()

        return {
            "connection_id": str(connection.id),
            "provider": provider_name,
            "display_name": user_info.get("name") or user_info.get("email") or provider_name,
            "scope": scope,
        }

    async def get_connection(self, connection_id: uuid.UUID) -> OAuthConnection | None:
        result = await self.uow.session.execute(
            select(OAuthConnection).where(OAuthConnection.id == connection_id)
        )
        return result.scalars().first()

    async def get_connection_by_provider(
        self,
        user_id: uuid.UUID,
        provider_name: str,
    ) -> OAuthConnection | None:
        provider = await self.get_provider(provider_name)
        if provider is None:
            return None
        result = await self.uow.session.execute(
            select(OAuthConnection).where(
                OAuthConnection.user_id == user_id,
                OAuthConnection.provider_id == provider.id,
                OAuthConnection.status == "active",
            )
        )
        return result.scalars().first()

    async def refresh_token(self, connection_id: uuid.UUID) -> dict[str, Any]:
        connection = await self.get_connection(connection_id)
        if connection is None:
            raise OAuthError("Connection not found")

        provider = await self.uow.session.execute(
            select(OAuthProvider).where(OAuthProvider.id == connection.provider_id)
        )
        provider_row = provider.scalars().first()
        if provider_row is None:
            raise OAuthError("Provider not found")

        if not connection.refresh_token_encrypted:
            raise OAuthError("No refresh token available")

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                provider_row.token_url,
                data={
                    "grant_type": "refresh_token",
                    "client_id": provider_row.client_id,
                    "client_secret": self._decrypt(provider_row.client_secret_encrypted),
                    "refresh_token": self._decrypt(connection.refresh_token_encrypted),
                },
            )
            if resp.status_code != 200:
                raise OAuthError(f"Token refresh failed: {resp.status_code} {resp.text}")
            token_data = resp.json()

        access_token = token_data.get("access_token")
        refresh_token = token_data.get(
            "refresh_token", self._decrypt(connection.refresh_token_encrypted)
        )
        expires_in = token_data.get("expires_in")

        expires_at = None
        if expires_in:
            expires_at = datetime.now(UTC) + timedelta(seconds=int(expires_in))

        await self.uow.oauth_connections.update(
            connection,
            access_token_encrypted=self._encrypt(access_token),
            refresh_token_encrypted=self._encrypt(refresh_token),
            expires_at=expires_at,
        )
        await self.uow.commit()
        return {"success": True, "expires_at": expires_at.isoformat() if expires_at else None}

    async def revoke(self, connection_id: uuid.UUID) -> None:
        connection = await self.get_connection(connection_id)
        if connection is None:
            raise OAuthError("Connection not found")
        await self.uow.oauth_connections.update(connection, status="revoked")
        await self.uow.commit()

    async def _validate_state(self, provider_name: str, state: str) -> OAuthState:
        result = await self.uow.session.execute(
            select(OAuthState).where(
                OAuthState.provider == provider_name,
                OAuthState.state == state,
                OAuthState.expires_at > datetime.now(UTC),
            )
        )
        state_obj = result.scalars().first()
        if state_obj is None:
            raise OAuthError("Invalid or expired state")
        return state_obj

    async def _fetch_user_info(self, provider: str, access_token: str) -> dict[str, Any]:
        user_info_urls = {
            "github": "https://api.github.com/user",
            "google": "https://www.googleapis.com/oauth2/v2/userinfo",
            "notion": "https://api.notion.com/v1/users/me",
            "slack": "https://slack.com/api/auth.test",
        }
        url = user_info_urls.get(provider)
        if not url:
            return {}
        async with httpx.AsyncClient(timeout=15) as client:
            headers = {"Authorization": f"Bearer {access_token}"}
            if provider == "notion":
                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Notion-Version": "2022-06-28",
                }
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                return {}
            return resp.json()

    @staticmethod
    def _generate_code_challenge(verifier: str) -> str:
        import base64
        import hashlib
        challenge = hashlib.sha256(verifier.encode()).digest()
        return base64.urlsafe_b64encode(challenge).decode().rstrip("=")

    @staticmethod
    def _encrypt(value: str) -> str:
        from cryptography.fernet import Fernet
        key = settings.ENCRYPTION_KEY.encode() if settings.ENCRYPTION_KEY else Fernet.generate_key()
        f = Fernet(key)
        return f.encrypt(value.encode()).decode()

    @staticmethod
    def _decrypt(value: str) -> str:
        from cryptography.fernet import Fernet
        key = settings.ENCRYPTION_KEY.encode() if settings.ENCRYPTION_KEY else Fernet.generate_key()
        f = Fernet(key)
        return f.decrypt(value.encode()).decode()
