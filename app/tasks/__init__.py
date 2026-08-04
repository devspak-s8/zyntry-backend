from __future__ import annotations

from app.workers.celery_app import celery_app
from app.tasks import runtimes, knowledge, webhooks, workflows, scheduler, notifications, billing, audit, security, analytics, cleanup


@celery_app.task(name="app.tasks.health_check")
def health_check() -> str:
    return "ok"
