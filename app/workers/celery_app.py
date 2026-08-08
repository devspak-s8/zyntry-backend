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
        "run-security-scan": {
            "task": "app.tasks.security.run_security_scan",
            "schedule": 3600.0,
        },
        "expire-temporary-bans": {
            "task": "app.tasks.security.expire_bans",
            "schedule": 3600.0,
        },
        "cleanup-expired-sessions": {
            "task": "app.tasks.cleanup.expired_sessions",
            "schedule": 86400.0,
        },
        "cleanup-expired-refresh-tokens": {
            "task": "app.tasks.cleanup.expired_refresh_tokens",
            "schedule": 86400.0,
        },
        "cleanup-revoked-tokens": {
            "task": "app.tasks.cleanup.revoked_tokens",
            "schedule": 86400.0,
        },
        "cleanup-old-request-logs": {
            "task": "app.tasks.cleanup.old_request_logs",
            "schedule": 604800.0,
        },
        "cleanup-old-audit-logs": {
            "task": "app.tasks.cleanup.old_audit_logs",
            "schedule": 604800.0,
        },
        "cleanup-old-webhook-deliveries": {
            "task": "app.tasks.cleanup.old_webhook_deliveries",
            "schedule": 604800.0,
        },
    },
)
