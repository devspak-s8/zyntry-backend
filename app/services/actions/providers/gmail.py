from __future__ import annotations

from typing import Any

import httpx

from app.schemas.actions import ActionDefinition, ActionResponse
from app.services.actions.base import BaseActionProvider


class GmailActionProvider(BaseActionProvider):
    provider_name = "gmail"

    def __init__(self, credentials: dict[str, Any] | None = None) -> None:
        self._token = (credentials or {}).get("access_token")
        self._base_url = "https://gmail.googleapis.com"
        if not self._token:
            raise ValueError("Gmail access token is required")

    def list_actions(self) -> list[ActionDefinition]:
        return [
            ActionDefinition(name="list_messages", description="List messages", provider=self.provider_name, risk="low"),
            ActionDefinition(name="get_message", description="Get a message", provider=self.provider_name, risk="low"),
            ActionDefinition(name="search_messages", description="Search messages", provider=self.provider_name, risk="low"),
            ActionDefinition(name="send_message", description="Send an email", provider=self.provider_name, risk="medium"),
            ActionDefinition(name="reply_message", description="Reply to an email", provider=self.provider_name, risk="medium"),
            ActionDefinition(name="draft_message", description="Create a draft", provider=self.provider_name, risk="low"),
            ActionDefinition(name="archive_message", description="Archive a message", provider=self.provider_name, risk="low"),
            ActionDefinition(name="delete_message", description="Delete a message", provider=self.provider_name, risk="high", required_permissions=["write"]),
            ActionDefinition(name="mark_read", description="Mark as read", provider=self.provider_name, risk="low"),
            ActionDefinition(name="list_labels", description="List labels", provider=self.provider_name, risk="low"),
            ActionDefinition(name="create_label", description="Create a label", provider=self.provider_name, risk="low"),
        ]

    async def validate(self, action: str, arguments: dict[str, Any]) -> bool:
        required = {"send_message": ["to", "subject", "body"], "reply_message": ["message_id", "body"], "search_messages": ["query"]}
        params = required.get(action, [])
        return all(p in arguments for p in params)

    async def execute(self, action: str, arguments: dict[str, Any], context: dict[str, Any]) -> ActionResponse:
        try:
            headers = {"Authorization": f"Bearer {self._token}"}
            async with httpx.AsyncClient(timeout=30) as client:
                if action == "list_messages":
                    resp = await client.get(f"{self._base_url}/gmail/v1/users/me/messages", headers=headers, params={"maxResults": arguments.get("max_results", 10)})
                    return ActionResponse(success=True, result=resp.json())
                elif action == "get_message":
                    resp = await client.get(f"{self._base_url}/gmail/v1/users/me/messages/{arguments['message_id']}", headers=headers)
                    return ActionResponse(success=True, result=resp.json())
                elif action == "search_messages":
                    resp = await client.get(f"{self._base_url}/gmail/v1/users/me/messages", headers=headers, params={"q": arguments["query"], "maxResults": arguments.get("max_results", 10)})
                    return ActionResponse(success=True, result=resp.json())
                elif action == "send_message":
                    message = f"From: me\nTo: {arguments['to']}\nSubject: {arguments['subject']}\n\n{arguments['body']}"
                    import base64
                    encoded = base64.urlsafe_b64encode(message.encode()).decode()
                    resp = await client.post(f"{self._base_url}/gmail/v1/users/me/messages/send", headers=headers, json={"raw": encoded})
                    return ActionResponse(success=resp.status_code in (200, 201), result=resp.json(), error=str(resp.text) if resp.status_code not in (200, 201) else None)
                elif action == "reply_message":
                    original = await client.get(f"{self._base_url}/gmail/v1/users/me/messages/{arguments['message_id']}", headers=headers)
                    headers_list = original.json().get("payload", {}).get("headers", [])
                    message_id = next((h["value"] for h in headers_list if h["name"] == "Message-ID"), "")
                    reply = f"In-Reply-To: {message_id}\nReferences: {message_id}\nFrom: me\nTo: {arguments.get('to', '')}\nSubject: {arguments.get('subject', 'Re:')}\n\n{arguments['body']}"
                    import base64
                    encoded = base64.urlsafe_b64encode(reply.encode()).decode()
                    resp = await client.post(f"{self._base_url}/gmail/v1/users/me/messages/send", headers=headers, json={"raw": encoded})
                    return ActionResponse(success=True, result=resp.json())
                elif action == "draft_message":
                    message = f"From: me\nTo: {arguments['to']}\nSubject: {arguments['subject']}\n\n{arguments['body']}"
                    import base64
                    encoded = base64.urlsafe_b64encode(message.encode()).decode()
                    resp = await client.post(f"{self._base_url}/gmail/v1/users/me/drafts", headers=headers, json={"message": {"raw": encoded}})
                    return ActionResponse(success=True, result=resp.json())
                elif action == "archive_message":
                    resp = await client.post(f"{self._base_url}/gmail/v1/users/me/messages/{arguments['message_id']}/modify", headers=headers, json={"removeLabelIds": ["INBOX"]})
                    return ActionResponse(success=True, result=resp.json())
                elif action == "delete_message":
                    resp = await client.delete(f"{self._base_url}/gmail/v1/users/me/messages/{arguments['message_id']}", headers=headers)
                    return ActionResponse(success=resp.status_code == 204, result={"deleted": resp.status_code == 204})
                elif action == "mark_read":
                    resp = await client.post(f"{self._base_url}/gmail/v1/users/me/messages/{arguments['message_id']}/modify", headers=headers, json={"removeLabelIds": ["UNREAD"]})
                    return ActionResponse(success=True, result=resp.json())
                elif action == "list_labels":
                    resp = await client.get(f"{self._base_url}/gmail/v1/users/me/labels", headers=headers)
                    return ActionResponse(success=True, result=resp.json())
                elif action == "create_label":
                    resp = await client.post(f"{self._base_url}/gmail/v1/users/me/labels", headers=headers, json={"name": arguments["name"]})
                    return ActionResponse(success=True, result=resp.json())
                else:
                    return ActionResponse(success=False, error=f"Unknown action: {action}")
        except httpx.HTTPStatusError as exc:
            return ActionResponse(success=False, error=f"Gmail API error: {exc.response.status_code} - {exc.response.text}")
        except Exception as exc:
            return ActionResponse(success=False, error=str(exc))
