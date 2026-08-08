from __future__ import annotations

from typing import Any

from app.events import NotificationChannel, NotificationEvent

_SENDER_MAP: dict[str, tuple[str, str]] = {
    "security": ("Zyntry Security", "security@zyntry.space"),
    "billing": ("Zyntry Billing", "billing@zyntry.space"),
    "support": ("Zyntry Support", "support@zyntry.space"),
    "status": ("Zyntry Status", "status@zyntry.space"),
    "default": ("Zyntry", "noreply@zyntry.space"),
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

        result = await send_email(
            template_name=event.event_type,
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
