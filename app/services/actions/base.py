from __future__ import annotations

from typing import Any, Protocol

from app.schemas.actions import ActionDefinition, ActionResponse


class BaseActionProvider(Protocol):
    provider_name: str

    async def execute(self, action: str, arguments: dict[str, Any], context: dict[str, Any]) -> ActionResponse:
        ...

    async def validate(self, action: str, arguments: dict[str, Any]) -> bool:
        ...

    def list_actions(self) -> list[ActionDefinition]:
        ...
