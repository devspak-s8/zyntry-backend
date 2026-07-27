from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class SendLibError(Exception):
    pass


class SendLibClient:
    def __init__(self, api_key: str, base_url: str = "https://sendlib.samueltuoyo.com") -> None:
        if not api_key:
            raise SendLibError("SendLib API key is required")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")

    async def send(
        self,
        to: str | list[str],
        subject: str,
        html: str,
        *,
        from_email: str | None = None,
        text: str | None = None,
        reply_to: str | None = None,
        cc: str | list[str] | None = None,
        bcc: str | list[str] | None = None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> dict:
        payload: dict[str, Any] = {
            "to": to,
            "subject": subject,
            "html": html,
        }

        if from_email:
            payload["from"] = from_email
        if text:
            payload["text"] = text
        if reply_to:
            payload["replyTo"] = reply_to
        if cc:
            payload["cc"] = cc
        if bcc:
            payload["bcc"] = bcc
        if attachments:
            payload["attachments"] = attachments

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{self._base_url}/api/send",
                json=payload,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
            )

        try:
            data = response.json()
        except Exception:
            data = {"raw": response.text}

        if response.status_code >= 400:
            logger.error("SendLib error %s: %s", response.status_code, data)
            raise SendLibError(f"SendLib failed with {response.status_code}: {data}")

        return data


_sendlib_client: SendLibClient | None = None


def get_sendlib_client() -> SendLibClient:
    global _sendlib_client
    if _sendlib_client is None:
        _sendlib_client = SendLibClient(api_key=settings.SENDLIB_API_KEY)
    return _sendlib_client
