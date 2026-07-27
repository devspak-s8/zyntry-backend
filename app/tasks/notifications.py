from __future__ import annotations

import logging

from celery import shared_task

from app.services.sendlib import get_sendlib_client

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def send_email_notification_task(self, user_id: str, title: str, message: str) -> dict:
    try:
        client = get_sendlib_client()
        result = client.send(
            to=[],
            subject=title,
            html=f"<p>{message}</p>",
        )
        logger.info("SendLib email sent", extra={"user_id": user_id, "title": title, "result": result})
        return {"status": "sent", "user_id": user_id, "title": title}
    except Exception as exc:
        logger.error("SendLib email failed", extra={"user_id": user_id, "error": str(exc)})
        return {"status": "error", "user_id": user_id, "error": str(exc)}


@shared_task(bind=True)
def send_in_app_notification_task(self, user_id: str, notification_type: str, title: str, message: str, data: dict | None = None) -> None:
    logger.info("In-app notification queued for user %s: %s", user_id, title)


@shared_task
def cleanup_old_logs_task(project_id: str | None = None, older_than_days: int = 30) -> None:
    logger.info("Cleanup task triggered for project %s older than %s days", project_id, older_than_days)
