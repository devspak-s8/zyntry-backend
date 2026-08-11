from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any


class ConnectorAuthError(Exception):
    pass


class ConnectorRateLimitError(Exception):
    pass


class ConnectorNetworkError(Exception):
    pass


class ConnectorDiscoveryError(Exception):
    pass


class BaseConnector(ABC):
    def __init__(self, project_id: str, source_id: str, config: dict, credentials: dict | None = None) -> None:
        self.project_id = project_id
        self.source_id = source_id
        self.config = config
        self.credentials = credentials or {}
        self.progress_callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None
        self._status: dict = {
            "status": "idle",
            "progress": 0,
            "message": "",
            "items_synced": 0,
        }

    async def emit_progress(self, event: str, message: str, **details: Any) -> None:
        if self.progress_callback is not None:
            await self.progress_callback(
                {"event": event, "message": message, "details": details}
            )

    @abstractmethod
    async def connect(self) -> dict:
        raise NotImplementedError

    @abstractmethod
    async def test(self) -> dict:
        raise NotImplementedError

    @abstractmethod
    async def discover(self) -> dict:
        raise NotImplementedError

    @abstractmethod
    async def sync(self, options: dict | None = None) -> dict:
        raise NotImplementedError

    @abstractmethod
    async def get_status(self) -> dict:
        raise NotImplementedError

    @abstractmethod
    async def disconnect(self) -> dict:
        raise NotImplementedError

    @abstractmethod
    async def refresh(self) -> dict:
        raise NotImplementedError

    @abstractmethod
    def validate(self) -> dict:
        raise NotImplementedError
