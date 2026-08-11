from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy import select

from app.core.config import settings
from app.models.oauth import OAuthConnection, OAuthProvider, OAuthState
from app.repositories import UnitOfWork


class OAuthError(Exception):
    pass


class OAuthService:
    _provider_cache: dict[str, OAuthProvider] = {}
    _connection_cache: dict[str, tuple[OAuthConnection, str]] = {}

    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def _get_provider_cached(self, name: str) -> OAuthProvider | None:
        if name in self._provider_cache:
            return self._provider_cache[name]
        result = await self.uow.session.execute(
            select(OAuthProvider).where(OAuthProvider.name == name, OAuthProvider.is_enabled)
        )
        provider = result.scalars().first()
        if provider is not None:
            self._provider_cache[name] = provider
        return provider

    async def _get_connection_cached(
        self,
        key: str,
        lookup,
    ) -> OAuthConnection | None:
        if key in self._connection_cache:
            return self._connection_cache[key][0]
        connection = await lookup()
        if connection is not None:
            self._connection_cache[key] = (connection, self._decrypt(connection.access_token_encrypted) if connection.access_token_encrypted else "")
        return connection

    def _invalidate_connection_cache(self, key: str) -> None:
        self._connection_cache.pop(key, None)

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
        return await self._get_provider_cached(name)

    async def authorize(
        self,
        provider_name: str,
        user_id: uuid.UUID,
        project_id: uuid.UUID | None = None,
        redirect_uri: str | None = None,
    ) -> dict[str, Any]:
        provider = await self._get_provider_cached(provider_name)
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
        url = f"{provider.auth_url}?{urlencode(params)}"
        return {"url": url, "state": state}

    async def callback(
        self,
        provider_name: str,
        code: str,
        state: str,
        project_id: uuid.UUID | None = None,
        expected_user_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        state_obj = await self._validate_state(provider_name, state)
        if expected_user_id is not None and state_obj.user_id != expected_user_id:
            raise OAuthError("OAuth state does not belong to the current user")
        if project_id is not None and state_obj.project_id != project_id:
            raise OAuthError("OAuth project does not match the authorization request")
        provider = await self.get_provider(provider_name)
        if provider is None:
            raise OAuthError(f"Provider '{provider_name}' not found")

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                provider.token_url,
                headers={"Accept": "application/json"},
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
        connection = await self.uow.oauth_connections.create(
            user_id=state_obj.user_id,
            project_id=project_id or state_obj.project_id,
            provider_id=provider.id,
            access_token_encrypted=self._encrypt(access_token),
            refresh_token_encrypted=self._encrypt(refresh_token) if refresh_token else None,
            expires_at=expires_at,
            scope=scope,
            metadata_={"user_info": user_info},
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
        provider = await self._get_provider_cached(provider_name)
        if provider is None:
            return None
        cache_key = f"user:{user_id}:{provider_name}"

        async def lookup():
            result = await self.uow.session.execute(
                select(OAuthConnection).where(
                    OAuthConnection.user_id == user_id,
                    OAuthConnection.provider_id == provider.id,
                    OAuthConnection.status == "active",
                )
            )
            return result.scalars().first()

        return await self._get_connection_cached(cache_key, lookup)

    async def get_connection_by_project(
        self,
        project_id: uuid.UUID,
        provider_name: str,
    ) -> OAuthConnection | None:
        provider = await self._get_provider_cached(provider_name)
        if provider is None:
            return None
        cache_key = f"project:{project_id}:{provider_name}"

        async def lookup():
            result = await self.uow.session.execute(
                select(OAuthConnection).where(
                    OAuthConnection.project_id == project_id,
                    OAuthConnection.provider_id == provider.id,
                    OAuthConnection.status == "active",
                )
            )
            return result.scalars().first()

        return await self._get_connection_cached(cache_key, lookup)

    async def pre_resolve_project_tokens(
        self,
        project_id: uuid.UUID,
    ) -> dict[str, dict[str, Any]]:
        result = await self.uow.session.execute(
            select(OAuthConnection)
            .where(OAuthConnection.project_id == project_id, OAuthConnection.status == "active")
        )
        connections = result.scalars().all()
        tokens: dict[str, dict[str, Any]] = {}
        for conn in connections:
            provider = await self.uow.session.execute(
                select(OAuthProvider).where(OAuthProvider.id == conn.provider_id)
            )
            provider_row = provider.scalars().first()
            if provider_row is None:
                continue
            self._provider_cache[provider_row.name] = provider_row
            if conn.access_token_encrypted:
                access_token = self._decrypt(conn.access_token_encrypted)
                if conn.expires_at and conn.expires_at <= datetime.now(UTC):
                    try:
                        await self.refresh_token(conn.id)
                        access_token = self._decrypt(conn.access_token_encrypted)
                    except Exception:
                        pass
                tokens[provider_row.name] = {"access_token": access_token}
        return tokens

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

        self._invalidate_connection_cache(f"user:{connection.user_id}:{provider_row.name}")
        self._invalidate_connection_cache(f"project:{connection.project_id}:{provider_row.name}")

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
