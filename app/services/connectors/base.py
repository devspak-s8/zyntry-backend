from __future__ import annotations

from abc import ABC, abstractmethod


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
        self._status: dict = {
            "status": "idle",
            "progress": 0,
            "message": "",
            "items_synced": 0,
        }

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
