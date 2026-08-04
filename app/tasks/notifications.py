from __future__ import annotations

import logging

from app.core.database import run_async
from app.core.logging import get_logger
from app.services.sendlib import SendLibError, get_sendlib_client
from app.workers.celery_app import celery_app

logger = get_logger("app.tasks.notifications")


@celery_app.task(name="app.tasks.notifications.send_email")
def send_email_notification_task(user_id: str, email: str, subject: str, html: str, text: str | None = None) -> dict:
    async def _run() -> dict:
        client = get_sendlib_client()
        try:
            result = await client.send(
                to=email,
                subject=subject,
                html=html,
                text=text,
            )
            return {"status": "sent", "user_id": user_id, "result": result}
        except SendLibError as exc:
            logger.error("SendLib email failed", extra={"user_id": user_id, "error": str(exc)})
            return {"status": "error", "user_id": user_id, "error": str(exc)}

    return run_async(_run())


@celery_app.task(name="app.tasks.notifications.send_in_app")
def send_in_app_notification_task(user_id: str, notification_type: str, title: str, message: str, data: dict | None = None) -> dict:
    async def _run() -> dict:
        from app.core.database import async_session_factory
        from app.models.notifications import Notification

        async with async_session_factory() as db:
            notif = Notification(
                user_id=user_id,
                type=notification_type,
                title=title,
                message=message,
                data=data or {},
                read=False,
            )
            db.add(notif)
            await db.commit()
            return {"status": "created", "user_id": user_id, "notification_id": str(notif.id)}

    return run_async(_run())
