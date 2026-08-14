from __future__ import annotations

from typing import Any

import httpx

from app.schemas.actions import ActionDefinition, ActionResponse
from app.services.actions.base import BaseActionProvider, get_http_client


class SlackActionProvider(BaseActionProvider):
    provider_name = "slack"

    def __init__(self, credentials: dict[str, Any] | None = None) -> None:
        self._token = (credentials or {}).get("token")

    def list_actions(self) -> list[ActionDefinition]:
        return [
            ActionDefinition(name="send_message", description="Send a message", provider=self.provider_name, risk="low"),
            ActionDefinition(name="reply_thread", description="Reply to a thread", provider=self.provider_name, risk="low"),
            ActionDefinition(name="read_channels", description="List channels", provider=self.provider_name, risk="low"),
            ActionDefinition(name="create_channel", description="Create a channel", provider=self.provider_name, risk="low"),
            ActionDefinition(name="invite_member", description="Invite a member", provider=self.provider_name, risk="medium"),
            ActionDefinition(name="search_messages", description="Search messages", provider=self.provider_name, risk="low"),
            ActionDefinition(name="upload_file", description="Upload a file", provider=self.provider_name, risk="low"),
            ActionDefinition(name="pin_message", description="Pin a message", provider=self.provider_name, risk="low"),
            ActionDefinition(name="schedule_message", description="Schedule a message", provider=self.provider_name, risk="low"),
        ]

    async def validate(self, action: str, arguments: dict[str, Any]) -> bool:
        required = {"send_message": ["channel", "text"], "reply_thread": ["channel", "thread_ts", "text"], "create_channel": ["name"]}
        params = required.get(action, [])
        return all(p in arguments for p in params)

    async def execute(self, action: str, arguments: dict[str, Any], context: dict[str, Any]) -> ActionResponse:
        if not self._token:
            return ActionResponse(success=False, error="No access token provided. Please connect your account via OAuth.")
        endpoints = {
            "send_message": ("chat.postMessage", {"channel": arguments.get("channel"), "text": arguments.get("text")}),
            "reply_thread": ("chat.postMessage", {"channel": arguments.get("channel"), "thread_ts": arguments.get("thread_ts"), "text": arguments.get("text")}),
            "read_channels": ("conversations.list", {"types": arguments.get("types", "public_channel,private_channel"), "limit": arguments.get("limit", 100)}),
            "create_channel": ("conversations.create", {"name": arguments.get("name"), "is_private": arguments.get("is_private", False)}),
            "invite_member": ("conversations.invite", {"channel": arguments.get("channel"), "users": arguments.get("users")}),
            "search_messages": ("search.messages", {"query": arguments.get("query", ""), "count": arguments.get("count", 20)}),
            "pin_message": ("pins.add", {"channel": arguments.get("channel"), "timestamp": arguments.get("timestamp")}),
            "schedule_message": ("chat.scheduleMessage", {"channel": arguments.get("channel"), "text": arguments.get("text"), "post_at": arguments.get("post_at")}),
        }
        if action == "upload_file":
            return ActionResponse(
                success=False,
                error="Slack file upload requires a file-upload session and is not supported by JSON invocation.",
            )
        selected = endpoints.get(action)
        if selected is None:
            return ActionResponse(success=False, error=f"Unknown action: {action}")
        endpoint, payload = selected
        payload = {key: value for key, value in payload.items() if value is not None}
        try:
            client = await get_http_client()
            response = await client.post(
                f"https://slack.com/api/{endpoint}",
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                json=payload,
            )
            response.raise_for_status()
            result = response.json()
            if not result.get("ok"):
                return ActionResponse(
                    success=False,
                    error=f"Slack API error: {result.get('error', 'unknown_error')}",
                )
            return ActionResponse(success=True, result=result)
        except httpx.HTTPStatusError as exc:
            return ActionResponse(
                success=False,
                error=f"Slack API error: {exc.response.status_code} - {exc.response.text}",
            )
        except Exception as exc:
            return ActionResponse(success=False, error=str(exc))
