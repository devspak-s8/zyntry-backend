from __future__ import annotations

import httpx
from typing import Any, Protocol

from app.schemas.actions import ActionDefinition, ActionResponse


class BaseActionProvider(Protocol):
    provider_name: str

    def __init__(self, credentials: dict[str, Any] | None = None) -> None:
        ...

    async def execute(
        self,
        action: str,
        arguments: dict[str, Any],
        context: dict[str, Any],
    ) -> ActionResponse:
        ...

    async def validate(
        self,
        action: str,
        arguments: dict[str, Any],
    ) -> bool:
        ...

    def list_actions(self) -> list[ActionDefinition]:
        ...


_shared_client = httpx.AsyncClient(timeout=30, follow_redirects=True)


async def get_http_client() -> httpx.AsyncClient:
    return _shared_client
