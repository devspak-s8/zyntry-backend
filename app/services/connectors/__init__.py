from __future__ import annotations

from typing import Any

from app.services.connectors.base import BaseConnector


class Registry:
    def __init__(self) -> None:
        self._connectors: dict[str, type[BaseConnector]] = {}

    def register(self, name: str, connector_class: type[BaseConnector]) -> None:
        self._connectors[name.lower()] = connector_class

    def get(self, name: str) -> type[BaseConnector]:
        connector = self._connectors.get(name.lower())
        if not connector:
            raise ValueError(f"Unsupported connector: {name}")
        return connector

    def create(self, name: str, **kwargs: Any) -> BaseConnector:
        connector_class = self.get(name)
        return connector_class(**kwargs)

    def list_supported(self) -> list[str]:
        return sorted(self._connectors.keys())


registry = Registry()

from app.services.connectors import github, gitlab, google_drive, notion, postgres, s3, slack, website  # noqa: E402
