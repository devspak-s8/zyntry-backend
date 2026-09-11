from __future__ import annotations

from app.tasks import (
    analytics,
    audit,
    billing,
    cleanup,
    knowledge,
    notifications,
    runtimes,
    scheduler,
    security,
    webhooks,
    workflows,
)
from app.workers.celery_app import celery_app


@celery_app.task(name="app.tasks.health_check")
def health_check() -> str:
    return "ok"
