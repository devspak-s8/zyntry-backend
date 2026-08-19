from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from app.core.database import run_async
from app.core.logging import get_logger
from app.models.billing import Budget, UsageLog
from app.services.billing import BillingService
from app.workers.celery_app import celery_app

logger = get_logger("app.tasks.billing")


@celery_app.task(name="app.tasks.billing.expire_billing_reservations")
def expire_billing_reservations() -> dict:
    async def _run() -> dict:
        from app.core.database import get_session
        from app.services.metered_billing import MeteredBillingService

        async for session in get_session():
            count = await MeteredBillingService(session).expire_reservations(limit=500)
            return {"status": "completed", "released": count}
        return {"status": "completed", "released": 0}

    return run_async(_run())


@celery_app.task(name="app.tasks.billing.send_budget_notification")
def send_budget_notification_task(user_id: str, event_type: str, limit: str) -> None:
    logger.info("Budget notification queued", extra={"user_id": user_id, "event_type": event_type})


@celery_app.task(name="app.tasks.billing.retry_failed_webhooks")
def retry_failed_webhooks() -> dict:
    async def _run() -> dict:
        from app.core.database import get_session
        from app.models.processed_webhook_events import ProcessedWebhookEvent
        from sqlalchemy import select
        from datetime import datetime, timedelta, timezone

        async for session in get_session():
            cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
            result = await session.execute(
                select(ProcessedWebhookEvent)
                .where(
                    ProcessedWebhookEvent.status == "failed",
                    ProcessedWebhookEvent.source == "internal",
                    ProcessedWebhookEvent.created_at >= cutoff,
                )
                .order_by(ProcessedWebhookEvent.created_at.asc())
                .limit(100)
            )
            failed = result.scalars().all()
            retried = 0
            for event in failed:
                payload = event.payload or {}
                subscription_id = payload.get("subscription_id")
                if subscription_id:
                    from app.tasks.webhooks import deliver_webhook_task
                    deliver_webhook_task.apply_async(
                        args=[subscription_id, event.event_type, payload.get("data", {}), event.event_id],
                        countdown=retried * 5,
                    )
                    retried += 1
            return {"status": "retried", "count": retried}

    return run_async(_run())


@celery_app.task(name="app.tasks.billing.generate_billing_summary")
def generate_billing_summary() -> dict:
    async def _run() -> dict:
        from app.core.database import get_session
        from sqlalchemy import select, func

        async for session in get_session():
            now = datetime.now(timezone.utc)
            start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)

            result = await session.execute(
                select(
                    func.sum(UsageLog.cost).label("total_cost"),
                    func.sum(UsageLog.requests).label("total_requests"),
                    func.sum(UsageLog.input_tokens).label("total_input_tokens"),
                    func.sum(UsageLog.output_tokens).label("total_output_tokens"),
                    UsageLog.provider,
                    UsageLog.model,
                )
                .where(UsageLog.created_at >= start_of_day)
                .group_by(UsageLog.provider, UsageLog.model)
            )
            rows = result.all()

            summary = {
                "generated_at": now.isoformat(),
                "total_cost": float(sum((row.total_cost or Decimal("0")) for row in rows)),
                "total_requests": sum(row.total_requests or 0 for row in rows),
                "total_input_tokens": sum(row.total_input_tokens or 0 for row in rows),
                "total_output_tokens": sum(row.total_output_tokens or 0 for row in rows),
                "by_provider_model": [
                    {
                        "provider": row.provider,
                        "model": row.model,
                        "cost": float(row.total_cost or Decimal("0")),
                        "requests": row.total_requests or 0,
                    }
                    for row in rows
                ],
            }
            logger.info("Billing summary generated", extra=summary)
            return summary

    return run_async(_run())


@celery_app.task(name="app.tasks.billing.clean_expired_sessions")
def clean_expired_sessions() -> dict:
    async def _run() -> dict:
        from app.core.database import get_session
        from app.models.users import RefreshToken, Session
        from sqlalchemy import delete

        async for session in get_session():
            now = datetime.now(timezone.utc)

            await session.execute(
                delete(Session).where(Session.expires_at < now, Session.revoked == False)
            )
            await session.execute(
                delete(RefreshToken).where(RefreshToken.expires_at < now, RefreshToken.revoked == False)
            )
            await session.commit()
            return {"status": "cleaned"}

    return run_async(_run())


@celery_app.task(name="app.tasks.billing.process_auto_top_up")
def process_auto_top_up(user_id: str) -> dict:
    async def _run() -> dict:
        uid = uuid.UUID(user_id)
        async for session in get_session():
            billing = BillingService(session)
            from app.repositories import UnitOfWork

            uow = UnitOfWork(session)
            budget = await uow.budgets.get_by_user(uid)
            if not budget or not budget.auto_top_up_enabled or not budget.auto_top_up_threshold or not budget.auto_top_up_amount:
                return {"status": "skipped", "reason": "auto_top_up_not_configured"}

            wallet = await billing.get_wallet(uid)
            if wallet.balance >= budget.auto_top_up_threshold:
                return {"status": "skipped", "reason": "balance_above_threshold"}

            try:
                await billing.add_credit(
                    user_id=uid,
                    amount=budget.auto_top_up_amount,
                    reason="Auto top-up",
                    reference_id=f"auto_topup_{user_id}_{datetime.now(timezone.utc).isoformat()}",
                )
                return {"status": "credited", "amount": float(budget.auto_top_up_amount)}
            except Exception as exc:
                logger.error("Auto top-up failed", extra={"user_id": user_id, "error": str(exc)})
                return {"status": "error", "error": str(exc)}

    return run_async(_run())


@celery_app.task(name="app.tasks.billing.reset_monthly_budgets")
def reset_monthly_budgets() -> dict:
    async def _run() -> dict:
        from app.core.database import get_session
        from sqlalchemy import update

        async for session in get_session():
            await session.execute(
                update(Budget)
                .where(Budget.monthly_limit.is_not(None))
                .values(
                    current_spend=Decimal("0.0000"),
                    warning_80_sent=False,
                    warning_90_sent=False,
                    limit_reached=False,
                )
            )
            await session.commit()
            return {"status": "reset"}

    return run_async(_run())
