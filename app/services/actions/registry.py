from __future__ import annotations

from typing import Any

from app.schemas.actions import ActionDefinition


class ActionRegistry:
    _providers: dict[str, Any] = {}

    @classmethod
    def register(cls, provider: Any) -> None:
        cls._providers[provider.provider_name] = provider

    @classmethod
    def get_provider(cls, name: str) -> Any | None:
        return cls._providers.get(name)

    @classmethod
    def list_providers(cls) -> list[str]:
        return list(cls._providers.keys())

    @classmethod
    def list_actions(cls, provider: str | None = None) -> list[ActionDefinition]:
        actions: list[ActionDefinition] = []
        providers = [cls._providers[provider]] if provider else cls._providers.values()
        for p in providers:
            actions.extend(p.list_actions())
        return actions

    @classmethod
    async def execute(cls, provider_name: str, action: str, arguments: dict[str, Any], context: dict[str, Any]) -> Any:
        provider = cls.get_provider(provider_name)
        if not provider:
            raise ValueError(f"Provider '{provider_name}' not found")
        if not await provider.validate(action, arguments):
            raise ValueError(f"Invalid arguments for action '{action}' on provider '{provider_name}'")
        return await provider.execute(action, arguments, context)
