from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.events import NotificationChannel, NotificationEvent

logger = logging.getLogger(__name__)

_SENDER_MAP: dict[str, tuple[str, str]] = {
    "security": ("Zyntry Security", "security@zyntry.space"),
    "billing": ("Zyntry Billing", "billing@zyntry.space"),
    "support": ("Zyntry Support", "support@zyntry.space"),
    "status": ("Zyntry Status", "status@zyntry.space"),
    "default": ("Zyntry", "noreply@zyntry.space"),
}

_EMAIL_TEMPLATE_MAP: dict[str, str] = {
    "auth.welcome": "welcome",
    "auth.verify_email": "verify_email",
    "auth.email_verified": "email_verified",
    "auth.password_reset": "password_reset",
    "auth.password_changed": "password_changed",
}


class NotificationWorker:
    def __init__(self) -> None:
        self._channels: dict[NotificationChannel, Any] = {
            NotificationChannel.EMAIL: self._send_email,
            NotificationChannel.WEBHOOK: self._send_webhook,
            NotificationChannel.REALTIME: self._send_realtime,
            NotificationChannel.SLACK: self._send_slack,
            NotificationChannel.DISCORD: self._send_discord,
        }

    async def process(self, event: NotificationEvent) -> dict[str, Any]:
        results: dict[str, Any] = {}
        for channel in event.channels:
            handler = self._channels.get(channel)
            if handler is None:
                continue
            try:
                results[channel.value] = await handler(event)
            except Exception as exc:
                results[channel.value] = {"success": False, "error": str(exc)}
        return results

    async def _send_email(self, event: NotificationEvent) -> dict[str, Any]:
        from app.emails import send_email

        category = event.category or "general"
        sender_name, sender_email = _SENDER_MAP.get(category, _SENDER_MAP["default"])
        if event.sender_name:
            sender_name = event.sender_name
        if event.sender_email:
            sender_email = event.sender_email

        reply_to = event.reply_to or (
            "support@zyntry.space" if category == "support" else None
        )

        template_name = _EMAIL_TEMPLATE_MAP.get(
            event.event_type, event.event_type.replace(".", "_")
        )
        result = await send_email(
            template_name=template_name,
            to=event.recipient,
            reply_to=reply_to,
            from_email=sender_email,
            from_name=sender_name,
            category=category,
            priority=event.priority.value,
            **event.data,
        )
        return result

    async def _send_webhook(self, event: NotificationEvent) -> dict[str, Any]:
        return {"success": True, "channel": "webhook", "event": event.event_type}

    async def _send_realtime(self, event: NotificationEvent) -> dict[str, Any]:
        return {"success": True, "channel": "realtime", "event": event.event_type}

    async def _send_slack(self, event: NotificationEvent) -> dict[str, Any]:
        return {"success": True, "channel": "slack", "event": event.event_type}

    async def _send_discord(self, event: NotificationEvent) -> dict[str, Any]:
        return {"success": True, "channel": "discord", "event": event.event_type}


notification_worker = NotificationWorker()


async def publish_notification(event: NotificationEvent) -> dict[str, Any]:
    return await notification_worker.process(event)


async def _safe_fire(coro: Any) -> None:
    try:
        result = await coro
        if isinstance(result, dict):
            failures = {
                channel: outcome
                for channel, outcome in result.items()
                if isinstance(outcome, dict) and outcome.get("success") is False
            }
            if failures:
                logger.error("Notification delivery failed: %s", failures)
    except Exception as exc:
        logger.exception("Notification task failed: %s", exc)


def enqueue_notification(event: NotificationEvent) -> None:
    asyncio.create_task(_safe_fire(notification_worker.process(event)))
