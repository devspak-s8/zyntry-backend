from __future__ import annotations

from typing import Any

from app.schemas.actions import ActionDefinition, ActionResponse
from app.services.actions.base import BaseActionProvider


class BoxActionProvider(BaseActionProvider):
    provider_name = "box"

    def __init__(self, credentials: dict[str, Any] | None = None) -> None:
        self._token = (credentials or {}).get("access_token")
        if not self._token:
            raise ValueError("Box access token is required")

    def list_actions(self) -> list[ActionDefinition]:
        return [
            ActionDefinition(name="list_files", description="List files", provider=self.provider_name, risk="low"),
            ActionDefinition(name="upload_file", description="Upload a file", provider=self.provider_name, risk="low"),
            ActionDefinition(name="download_file", description="Download a file", provider=self.provider_name, risk="low"),
            ActionDefinition(name="search_files", description="Search files", provider=self.provider_name, risk="low"),
            ActionDefinition(name="delete_file", description="Delete a file", provider=self.provider_name, risk="high", required_permissions=["write"]),
            ActionDefinition(name="share_file", description="Share a file", provider=self.provider_name, risk="medium"),
        ]

    async def validate(self, action: str, arguments: dict[str, Any]) -> bool:
        return True

    async def execute(self, action: str, arguments: dict[str, Any], context: dict[str, Any]) -> ActionResponse:
        return ActionResponse(success=False, error="Box actions not yet implemented")


class OneDriveActionProvider(BaseActionProvider):
    provider_name = "onedrive"

    def __init__(self, credentials: dict[str, Any] | None = None) -> None:
        self._token = (credentials or {}).get("access_token")
        self._base_url = "https://graph.microsoft.com/v1.0"
        if not self._token:
            raise ValueError("OneDrive access token is required")

    def list_actions(self) -> list[ActionDefinition]:
        return [
            ActionDefinition(name="list_files", description="List files", provider=self.provider_name, risk="low"),
            ActionDefinition(name="upload_file", description="Upload a file", provider=self.provider_name, risk="low"),
            ActionDefinition(name="download_file", description="Download a file", provider=self.provider_name, risk="low"),
            ActionDefinition(name="search_files", description="Search files", provider=self.provider_name, risk="low"),
            ActionDefinition(name="delete_file", description="Delete a file", provider=self.provider_name, risk="high", required_permissions=["write"]),
            ActionDefinition(name="share_file", description="Share a file", provider=self.provider_name, risk="medium"),
        ]

    async def validate(self, action: str, arguments: dict[str, Any]) -> bool:
        return True

    async def execute(self, action: str, arguments: dict[str, Any], context: dict[str, Any]) -> ActionResponse:
        return ActionResponse(success=False, error="OneDrive actions not yet implemented")
