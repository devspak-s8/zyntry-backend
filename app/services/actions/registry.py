from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from app.repositories import UnitOfWork
from app.schemas.actions import ActionDefinition
from app.services.actions.base import BaseActionProvider
from app.services.oauth.service import OAuthService


class ActionRegistry:
    _providers: dict[str, type[BaseActionProvider]] = {}

    @classmethod
    def register(cls, provider: type[BaseActionProvider]) -> None:
        cls._providers[provider.provider_name] = provider

    @classmethod
    def get_provider(cls, name: str) -> type[BaseActionProvider] | None:
        return cls._providers.get(name)

    @classmethod
    def list_providers(cls) -> list[str]:
        return list(cls._providers.keys())

    @classmethod
    def list_actions(cls, provider: str | None = None) -> list[ActionDefinition]:
        actions: list[ActionDefinition] = []
        providers = [cls._providers[provider]] if provider else cls._providers.values()
        for provider_cls in providers:
            actions.extend(provider_cls().list_actions())
        return actions

    @classmethod
    async def execute(
        cls,
        provider_name: str,
        action: str,
        arguments: dict[str, Any],
        context: dict[str, Any],
        uow: UnitOfWork | None = None,
    ) -> Any:
        provider_cls = cls.get_provider(provider_name)
        if not provider_cls:
            raise ValueError(f"Provider '{provider_name}' not found")

        credentials: dict[str, Any] = {}
        if uow is not None:
            project_id_str = context.get("project_id")
            user_id_str = context.get("user_id")
            oauth_service = OAuthService(uow)
            connection = None
            if project_id_str:
                try:
                    connection = await oauth_service.get_connection_by_project(
                        uuid.UUID(project_id_str), provider_name,
                    )
                except Exception:
                    pass
            if connection is None and user_id_str:
                try:
                    connection = await oauth_service.get_connection_by_provider(
                        uuid.UUID(user_id_str), provider_name,
                    )
                except Exception:
                    pass
            if connection and connection.access_token_encrypted:
                access_token = oauth_service._decrypt(connection.access_token_encrypted)
                if connection.expires_at and connection.expires_at <= datetime.now(UTC):
                    await oauth_service.refresh_token(connection.id)
                    access_token = oauth_service._decrypt(connection.access_token_encrypted)
                credentials["access_token"] = access_token

        provider = provider_cls(credentials=credentials if credentials else None)
        if not await provider.validate(action, arguments):
            raise ValueError(
                f"Invalid arguments for action '{action}' on provider '{provider_name}'"
            )
        return await provider.execute(action, arguments, context)
