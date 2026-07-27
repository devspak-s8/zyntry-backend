from __future__ import annotations

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "zyntra",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        "run-scheduled-syncs": {
            "task": "app.tasks.scheduler.run_scheduled_syncs",
            "schedule": 300.0,
        },
        "generate-billing-summary": {
            "task": "app.tasks.billing.generate_billing_summary",
            "schedule": 86400.0,
        },
        "reset-monthly-budgets": {
            "task": "app.tasks.billing.reset_monthly_budgets",
            "schedule": 86400.0,
        },
        "clean-expired-payment-sessions": {
            "task": "app.tasks.billing.clean_expired_sessions",
            "schedule": 3600.0,
        },
    },
)
