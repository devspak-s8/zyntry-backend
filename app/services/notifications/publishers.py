from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.events import NotificationEvent
from app.services.notifications import publish_notification

logger = logging.getLogger(__name__)


async def _safe_fire(coro: Any) -> None:
    try:
        await coro
    except Exception as exc:
        logger.exception("Notification task failed: %s", exc)


def fire_notification(event: NotificationEvent) -> None:
    asyncio.create_task(_safe_fire(publish_notification(event)))


async def send_project_created(to: str, user_name: str | None, project_name: str) -> dict[str, Any]:
    event = NotificationEvent(
        event_type="project.created",
        recipient=to,
        data={"user_name": user_name, "project_name": project_name},
        category="general",
    )
    return await publish_notification(event)


async def send_auth_welcome(to: str, user_name: str | None = None) -> dict[str, Any]:
    event = NotificationEvent(
        event_type="auth.welcome",
        recipient=to,
        data={"user_name": user_name},
        category="general",
    )
    return await publish_notification(event)


async def send_verification_email(to: str, user_name: str | None, token: str) -> dict[str, Any]:
    event = NotificationEvent(
        event_type="auth.verify_email",
        recipient=to,
        data={"user_name": user_name, "token": token},
        category="security",
        sender_name="Zyntry Security",
        sender_email="security@zyntry.space",
    )
    return await publish_notification(event)


async def send_email_verified(to: str, user_name: str | None = None) -> dict[str, Any]:
    event = NotificationEvent(
        event_type="auth.email_verified",
        recipient=to,
        data={"user_name": user_name},
        category="security",
        sender_name="Zyntry Security",
        sender_email="security@zyntry.space",
    )
    return await publish_notification(event)


async def send_password_reset(to: str, user_name: str | None, token: str) -> dict[str, Any]:
    event = NotificationEvent(
        event_type="auth.password_reset",
        recipient=to,
        data={"user_name": user_name, "token": token},
        category="security",
        sender_name="Zyntry Security",
        sender_email="security@zyntry.space",
    )
    return await publish_notification(event)


async def send_password_changed(to: str, user_name: str | None = None) -> dict[str, Any]:
    event = NotificationEvent(
        event_type="auth.password_changed",
        recipient=to,
        data={"user_name": user_name},
        category="security",
        sender_name="Zyntry Security",
        sender_email="security@zyntry.space",
    )
    return await publish_notification(event)


async def send_api_key_created(to: str, key_name: str) -> dict[str, Any]:
    event = NotificationEvent(
        event_type="api_key.created",
        recipient=to,
        data={"key_name": key_name},
        category="security",
        sender_name="Zyntry Security",
        sender_email="security@zyntry.space",
    )
    return await publish_notification(event)


async def send_api_key_rotated(to: str, key_name: str) -> dict[str, Any]:
    event = NotificationEvent(
        event_type="api_key.rotated",
        recipient=to,
        data={"key_name": key_name},
        category="security",
        sender_name="Zyntry Security",
        sender_email="security@zyntry.space",
    )
    return await publish_notification(event)


async def send_api_key_revoked(to: str, key_name: str) -> dict[str, Any]:
    event = NotificationEvent(
        event_type="api_key.revoked",
        recipient=to,
        data={"key_name": key_name},
        category="security",
        sender_name="Zyntry Security",
        sender_email="security@zyntry.space",
    )
    return await publish_notification(event)


async def send_provider_connected(to: str, provider: str, display_name: str | None = None) -> dict[str, Any]:
    event = NotificationEvent(
        event_type="provider.connected",
        recipient=to,
        data={"provider": provider, "source_name": display_name or provider},
        category="general",
    )
    return await publish_notification(event)


async def send_provider_disconnected(to: str, provider: str, display_name: str | None = None) -> dict[str, Any]:
    event = NotificationEvent(
        event_type="provider.disconnected",
        recipient=to,
        data={"provider": provider, "display_name": display_name or provider},
        category="general",
    )
    return await publish_notification(event)


async def send_runtime_build_started(to: str, runtime_name: str) -> dict[str, Any]:
    event = NotificationEvent(
        event_type="runtime.build_started",
        recipient=to,
        data={"runtime_name": runtime_name},
        category="general",
    )
    return await publish_notification(event)


async def send_runtime_ready(to: str, runtime_name: str) -> dict[str, Any]:
    event = NotificationEvent(
        event_type="runtime.build_completed",
        recipient=to,
        data={"runtime_name": runtime_name},
        category="general",
    )
    return await publish_notification(event)


async def send_runtime_failed(to: str, runtime_name: str, error: str | None = None) -> dict[str, Any]:
    event = NotificationEvent(
        event_type="runtime.build_failed",
        recipient=to,
        data={"runtime_name": runtime_name, "error": error},
        category="general",
    )
    return await publish_notification(event)
