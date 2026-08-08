from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class SendByteError(Exception):
    pass


class SendByteClient:
    def __init__(self, api_key: str, base_url: str = "https://api.sendbyte.africa") -> None:
        if not api_key:
            raise SendByteError("SendByte API key is required")
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
                f"{self._base_url}/v1/emails",
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
            logger.error("SendByte error %s: %s", response.status_code, data)
            raise SendByteError(f"SendByte failed with {response.status_code}: {data}")

        return data


_sendbyte_client: SendByteClient | None = None


def get_sendbyte_client() -> SendByteClient:
    global _sendbyte_client
    if _sendbyte_client is None:
        _sendbyte_client = SendByteClient(api_key=settings.SENDBYTE_KEY)
    return _sendbyte_client
