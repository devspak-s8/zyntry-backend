from __future__ import annotations

from typing import Any

from app.schemas.actions import ActionDefinition, ActionResponse
from app.services.actions.base import BaseActionProvider


class GitLabActionProvider(BaseActionProvider):
    provider_name = "gitlab"

    def __init__(self, credentials: dict[str, Any] | None = None) -> None:
        self._token = (credentials or {}).get("token")
        self._base_url = (credentials or {}).get("base_url", "https://gitlab.com")
        if not self._token:
            raise ValueError("GitLab token is required")

    def list_actions(self) -> list[ActionDefinition]:
        return [
            ActionDefinition(name="list_projects", description="List projects", provider=self.provider_name, risk="low"),
            ActionDefinition(name="create_issue", description="Create an issue", provider=self.provider_name, risk="low"),
            ActionDefinition(name="create_merge_request", description="Create a merge request", provider=self.provider_name, risk="low"),
            ActionDefinition(name="list_commits", description="List commits", provider=self.provider_name, risk="low"),
            ActionDefinition(name="trigger_pipeline", description="Trigger a pipeline", provider=self.provider_name, risk="medium"),
        ]

    async def validate(self, action: str, arguments: dict[str, Any]) -> bool:
        return True

    async def execute(self, action: str, arguments: dict[str, Any], context: dict[str, Any]) -> ActionResponse:
        return ActionResponse(success=False, error="GitLab actions not yet implemented")
