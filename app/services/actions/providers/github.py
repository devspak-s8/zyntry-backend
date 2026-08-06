from __future__ import annotations

from typing import Any

import httpx

from app.schemas.actions import ActionDefinition, ActionResponse
from app.services.actions.base import BaseActionProvider


class GitHubActionProvider(BaseActionProvider):
    provider_name = "github"

    def __init__(self, credentials: dict[str, Any] | None = None) -> None:
        self._token = (credentials or {}).get("token")
        self._base_url = "https://api.github.com"
        if not self._token:
            raise ValueError("GitHub token is required")

    def list_actions(self) -> list[ActionDefinition]:
        return [
            ActionDefinition(name="search_repos", description="Search repositories", provider=self.provider_name, risk="low"),
            ActionDefinition(name="read_repo", description="Read repository details", provider=self.provider_name, risk="low"),
            ActionDefinition(name="read_readme", description="Read repository README", provider=self.provider_name, risk="low"),
            ActionDefinition(name="search_code", description="Search code in repository", provider=self.provider_name, risk="low"),
            ActionDefinition(name="create_repo", description="Create a new repository", provider=self.provider_name, risk="medium"),
            ActionDefinition(name="create_issue", description="Create an issue", provider=self.provider_name, risk="low"),
            ActionDefinition(name="close_issue", description="Close an issue", provider=self.provider_name, risk="medium", required_permissions=["write"]),
            ActionDefinition(name="update_issue", description="Update an issue", provider=self.provider_name, risk="low"),
            ActionDefinition(name="comment_issue", description="Comment on an issue", provider=self.provider_name, risk="low"),
            ActionDefinition(name="create_pr", description="Create a pull request", provider=self.provider_name, risk="medium"),
            ActionDefinition(name="review_pr", description="Review a pull request", provider=self.provider_name, risk="medium"),
            ActionDefinition(name="merge_pr", description="Merge a pull request", provider=self.provider_name, risk="high", required_permissions=["write"]),
            ActionDefinition(name="create_branch", description="Create a branch", provider=self.provider_name, risk="low"),
            ActionDefinition(name="delete_branch", description="Delete a branch", provider=self.provider_name, risk="high", required_permissions=["write"]),
            ActionDefinition(name="commit_file", description="Commit a file", provider=self.provider_name, risk="medium", required_permissions=["write"]),
            ActionDefinition(name="list_workflows", description="List GitHub Actions workflows", provider=self.provider_name, risk="low"),
            ActionDefinition(name="trigger_workflow", description="Trigger a workflow", provider=self.provider_name, risk="medium"),
            ActionDefinition(name="list_commits", description="List recent commits", provider=self.provider_name, risk="low"),
        ]

    async def validate(self, action: str, arguments: dict[str, Any]) -> bool:
        required = {"search_repos": ["query"], "read_repo": ["owner", "repo"], "create_repo": ["name"], "create_issue": ["owner", "repo", "title"], "create_pr": ["owner", "repo", "title", "head", "base"], "commit_file": ["owner", "repo", "path", "content", "message", "branch"]}
        params = required.get(action, [])
        return all(p in arguments for p in params)

    async def execute(self, action: str, arguments: dict[str, Any], context: dict[str, Any]) -> ActionResponse:
        try:
            headers = {"Authorization": f"Bearer {self._token}", "Accept": "application/vnd.github+json"}
            async with httpx.AsyncClient(timeout=30) as client:
                if action == "search_repos":
                    resp = await client.get(f"{self._base_url}/search/repositories", headers=headers, params={"q": arguments["query"]})
                    return ActionResponse(success=True, result=resp.json())
                elif action == "read_repo":
                    resp = await client.get(f"{self._base_url}/repos/{arguments['owner']}/{arguments['repo']}", headers=headers)
                    return ActionResponse(success=True, result=resp.json())
                elif action == "read_readme":
                    resp = await client.get(f"{self._base_url}/repos/{arguments['owner']}/{arguments['repo']}/readme", headers=headers)
                    return ActionResponse(success=True, result=resp.json())
                elif action == "search_code":
                    resp = await client.get(f"{self._base_url}/search/code", headers=headers, params={"q": arguments["query"]})
                    return ActionResponse(success=True, result=resp.json())
                elif action == "create_repo":
                    resp = await client.post(f"{self._base_url}/user/repos", headers=headers, json={"name": arguments["name"], "private": arguments.get("private", False)})
                    return ActionResponse(success=resp.status_code in (201,), result=resp.json(), error=str(resp.text) if resp.status_code not in (201,) else None)
                elif action == "create_issue":
                    resp = await client.post(f"{self._base_url}/repos/{arguments['owner']}/{arguments['repo']}/issues", headers=headers, json={"title": arguments["title"], "body": arguments.get("body", "")})
                    return ActionResponse(success=True, result=resp.json())
                elif action == "close_issue":
                    resp = await client.patch(f"{self._base_url}/repos/{arguments['owner']}/{arguments['repo']}/issues/{arguments['issue_number']}", headers=headers, json={"state": "closed"})
                    return ActionResponse(success=True, result=resp.json())
                elif action == "update_issue":
                    resp = await client.patch(f"{self._base_url}/repos/{arguments['owner']}/{arguments['repo']}/issues/{arguments['issue_number']}", headers=headers, json={"title": arguments.get("title"), "body": arguments.get("body")})
                    return ActionResponse(success=True, result=resp.json())
                elif action == "comment_issue":
                    resp = await client.post(f"{self._base_url}/repos/{arguments['owner']}/{arguments['repo']}/issues/{arguments['issue_number']}/comments", headers=headers, json={"body": arguments["body"]})
                    return ActionResponse(success=True, result=resp.json())
                elif action == "create_pr":
                    resp = await client.post(f"{self._base_url}/repos/{arguments['owner']}/{arguments['repo']}/pulls", headers=headers, json={"title": arguments["title"], "head": arguments["head"], "base": arguments["base"], "body": arguments.get("body", "")})
                    return ActionResponse(success=True, result=resp.json())
                elif action == "review_pr":
                    resp = await client.post(f"{self._base_url}/repos/{arguments['owner']}/{arguments['repo']}/pulls/{arguments['pull_number']}/reviews", headers=headers, json={"event": arguments.get("event", "APPROVE"), "body": arguments.get("body", "")})
                    return ActionResponse(success=True, result=resp.json())
                elif action == "merge_pr":
                    resp = await client.put(f"{self._base_url}/repos/{arguments['owner']}/{arguments['repo']}/pulls/{arguments['pull_number']}/merge", headers=headers, json={"commit_title": arguments.get("commit_title", ""), "merge_method": arguments.get("merge_method", "merge")})
                    return ActionResponse(success=True, result=resp.json())
                elif action == "create_branch":
                    resp = await client.post(f"{self._base_url}/repos/{arguments['owner']}/{arguments['repo']}/git/refs", headers=headers, json={"ref": f"refs/heads/{arguments['branch']}", "sha": arguments["sha"]})
                    return ActionResponse(success=True, result=resp.json())
                elif action == "delete_branch":
                    resp = await client.delete(f"{self._base_url}/repos/{arguments['owner']}/{arguments['repo']}/git/refs/heads/{arguments['branch']}", headers=headers)
                    return ActionResponse(success=resp.status_code == 204, result={"deleted": resp.status_code == 204})
                elif action == "commit_file":
                    resp = await client.put(f"{self._base_url}/repos/{arguments['owner']}/{arguments['repo']}/contents/{arguments['path']}", headers=headers, json={"message": arguments["message"], "content": arguments["content"], "branch": arguments["branch"]})
                    return ActionResponse(success=True, result=resp.json())
                elif action == "list_workflows":
                    resp = await client.get(f"{self._base_url}/repos/{arguments['owner']}/{arguments['repo']}/actions/workflows", headers=headers)
                    return ActionResponse(success=True, result=resp.json())
                elif action == "trigger_workflow":
                    resp = await client.post(f"{self._base_url}/repos/{arguments['owner']}/{arguments['repo']}/actions/workflows/{arguments['workflow_id']}/dispatches", headers=headers, json={"ref": arguments["ref"]})
                    return ActionResponse(success=resp.status_code == 204, result={"triggered": resp.status_code == 204})
                elif action == "list_commits":
                    resp = await client.get(f"{self._base_url}/repos/{arguments['owner']}/{arguments['repo']}/commits", headers=headers, params={"per_page": arguments.get("per_page", 30)})
                    return ActionResponse(success=True, result=resp.json())
                else:
                    return ActionResponse(success=False, error=f"Unknown action: {action}")
        except httpx.HTTPStatusError as exc:
            return ActionResponse(success=False, error=f"GitHub API error: {exc.response.status_code} - {exc.response.text}")
        except Exception as exc:
            return ActionResponse(success=False, error=str(exc))
