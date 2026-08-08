from __future__ import annotations

from typing import Any

from app.schemas.actions import ActionDefinition, ActionResponse
from app.services.actions.base import BaseActionProvider


class JiraActionProvider(BaseActionProvider):
    provider_name = "jira"

    def __init__(self, credentials: dict[str, Any] | None = None) -> None:
        self._token = (credentials or {}).get("token")
        self._base_url = (credentials or {}).get("base_url", "https://api.atlassian.com")

    def list_actions(self) -> list[ActionDefinition]:
        return [
            ActionDefinition(name="create_issue", description="Create an issue", provider=self.provider_name, risk="low"),
            ActionDefinition(name="update_issue", description="Update an issue", provider=self.provider_name, risk="low"),
            ActionDefinition(name="assign_issue", description="Assign an issue", provider=self.provider_name, risk="medium"),
            ActionDefinition(name="transition_issue", description="Change issue status", provider=self.provider_name, risk="medium"),
            ActionDefinition(name="search_issues", description="Search issues", provider=self.provider_name, risk="low"),
            ActionDefinition(name="add_comment", description="Add a comment", provider=self.provider_name, risk="low"),
            ActionDefinition(name="create_sprint", description="Create a sprint", provider=self.provider_name, risk="low"),
            ActionDefinition(name="list_backlog", description="List backlog", provider=self.provider_name, risk="low"),
        ]

    async def validate(self, action: str, arguments: dict[str, Any]) -> bool:
        required = {"create_issue": ["project", "summary"], "update_issue": ["issue_key"], "assign_issue": ["issue_key", "assignee"]}
        params = required.get(action, [])
        return all(p in arguments for p in params)

    async def execute(self, action: str, arguments: dict[str, Any], context: dict[str, Any]) -> ActionResponse:
        if not self._token:
            return ActionResponse(success=False, error="No access token provided. Please connect your account via OAuth.")
        return ActionResponse(success=False, error="Jira actions not yet implemented")
