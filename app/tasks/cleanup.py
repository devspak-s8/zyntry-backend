from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.database import run_async
from app.core.logging import get_logger
from app.workers.celery_app import celery_app

logger = get_logger("app.tasks.cleanup")


def _affected_rows(result: Any) -> int:
    return int(result.rowcount or 0)


@celery_app.task(name="app.tasks.cleanup.expired_sessions")
def cleanup_expired_sessions_task() -> int:
    async def _run() -> int:
        from sqlalchemy import delete

        from app.core.database import async_session_factory
        from app.models.sessions import Session

        async with async_session_factory() as db:
            now = datetime.now(UTC)
            result = await db.execute(
                delete(Session).where(Session.expires_at < now)
            )
            await db.commit()
            count = _affected_rows(result)
            logger.info("Cleaned expired sessions", extra={"count": count})
            return count

    return run_async(_run())


@celery_app.task(name="app.tasks.cleanup.expired_refresh_tokens")
def cleanup_expired_refresh_tokens_task() -> int:
    async def _run() -> int:
        from sqlalchemy import delete

        from app.core.database import async_session_factory
        from app.models.refresh_tokens import RefreshToken

        async with async_session_factory() as db:
            now = datetime.now(UTC)
            result = await db.execute(
                delete(RefreshToken).where(RefreshToken.expires_at < now)
            )
            await db.commit()
            count = _affected_rows(result)
            logger.info("Cleaned expired refresh tokens", extra={"count": count})
            return count

    return run_async(_run())


@celery_app.task(name="app.tasks.cleanup.revoked_tokens")
def cleanup_revoked_tokens_task() -> int:
    async def _run() -> int:
        from sqlalchemy import delete

        from app.core.database import async_session_factory
        from app.models.refresh_tokens import RefreshToken
        from app.models.sessions import Session

        async with async_session_factory() as db:
            cutoff = datetime.now(UTC) - timedelta(days=30)
            session_result = await db.execute(
                delete(Session).where(Session.revoked.is_(True), Session.created_at < cutoff)
            )
            token_result = await db.execute(
                delete(RefreshToken).where(RefreshToken.revoked.is_(True), RefreshToken.created_at < cutoff)
            )
            await db.commit()
            sessions_deleted = _affected_rows(session_result)
            tokens_deleted = _affected_rows(token_result)
            total = sessions_deleted + tokens_deleted
            logger.info("Cleaned revoked tokens", extra={"sessions_deleted": sessions_deleted, "tokens_deleted": tokens_deleted})
            return total

    return run_async(_run())


@celery_app.task(name="app.tasks.cleanup.old_request_logs")
def cleanup_old_request_logs_task(older_than_days: int = 90) -> int:
    async def _run() -> int:
        from sqlalchemy import delete

        from app.core.database import async_session_factory
        from app.models.request_logs import RequestLog

        async with async_session_factory() as db:
            cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
            result = await db.execute(delete(RequestLog).where(RequestLog.created_at < cutoff))
            await db.commit()
            count = _affected_rows(result)
            logger.info("Cleaned old request logs", extra={"count": count, "older_than_days": older_than_days})
            return count

    return run_async(_run())


@celery_app.task(name="app.tasks.cleanup.old_build_artifacts")
def cleanup_old_build_artifacts_task(older_than_days: int = 7) -> int:
    async def _run() -> int:
        from sqlalchemy import delete

        from app.core.database import async_session_factory
        from app.models.runtimes import RuntimeBuildChunk

        async with async_session_factory() as db:
            cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
            result = await db.execute(
                delete(RuntimeBuildChunk).where(
                    RuntimeBuildChunk.runtime_id.is_(None),
                    RuntimeBuildChunk.created_at < cutoff,
                )
            )
            await db.commit()
            count = _affected_rows(result)
            logger.info("Cleaned old build artifacts", extra={"count": count, "older_than_days": older_than_days})
            return count

    return run_async(_run())


@celery_app.task(name="app.tasks.cleanup.expired_embedding_cache")
def cleanup_expired_embedding_cache_task() -> int:
    async def _run() -> int:
        from sqlalchemy import delete

        from app.core.database import async_session_factory
        from app.models.embedding_cache import EmbeddingCache

        async with async_session_factory() as db:
            now = datetime.now(UTC)
            result = await db.execute(
                delete(EmbeddingCache).where(
                    EmbeddingCache.expires_at.is_not(None),
                    EmbeddingCache.expires_at < now,
                )
            )
            await db.commit()
            count = _affected_rows(result)
            logger.info("Cleaned expired embedding cache", extra={"count": count})
            return count

    return run_async(_run())


@celery_app.task(name="app.tasks.cleanup.old_audit_logs")
def cleanup_old_audit_logs_task(older_than_days: int = 365) -> int:
    async def _run() -> int:
        from sqlalchemy import delete

        from app.admin.models import AdminAuditLog
        from app.core.database import async_session_factory

        async with async_session_factory() as db:
            cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
            result = await db.execute(
                delete(AdminAuditLog).where(AdminAuditLog.created_at < cutoff)
            )
            await db.commit()
            count = _affected_rows(result)
            logger.info("Cleaned old audit logs", extra={"count": count, "older_than_days": older_than_days})
            return count

    return run_async(_run())


@celery_app.task(name="app.tasks.cleanup.old_webhook_deliveries")
def cleanup_old_webhook_deliveries_task(older_than_days: int = 30) -> int:
    async def _run() -> int:
        from sqlalchemy import delete

        from app.core.database import async_session_factory
        from app.models.webhook_deliveries import WebhookDelivery

        async with async_session_factory() as db:
            cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
            result = await db.execute(
                delete(WebhookDelivery).where(WebhookDelivery.created_at < cutoff)
            )
            await db.commit()
            count = _affected_rows(result)
            logger.info("Cleaned old webhook deliveries", extra={"count": count, "older_than_days": older_than_days})
            return count

    return run_async(_run())


@celery_app.task(name="app.tasks.cleanup.daily_cleanup")
def daily_cleanup_task() -> dict[str, int]:
    async def _run() -> dict[str, int]:
        from sqlalchemy import delete

        from app.admin.models import AdminAuditLog
        from app.core.database import async_session_factory
        from app.models.refresh_tokens import RefreshToken
        from app.models.sessions import Session
        from app.models.webhook_deliveries import WebhookDelivery

        async with async_session_factory() as db:
            results: dict[str, int] = {}

            now = datetime.now(UTC)
            r = await db.execute(delete(Session).where(Session.expires_at < now))
            await db.commit()
            results["expired_sessions"] = _affected_rows(r)

            r = await db.execute(delete(RefreshToken).where(RefreshToken.expires_at < now))
            await db.commit()
            results["expired_refresh_tokens"] = _affected_rows(r)

            r = await db.execute(delete(AdminAuditLog).where(AdminAuditLog.created_at < datetime.now(UTC) - timedelta(days=365)))
            await db.commit()
            results["old_audit_logs"] = _affected_rows(r)

            r = await db.execute(delete(WebhookDelivery).where(WebhookDelivery.created_at < datetime.now(UTC) - timedelta(days=30)))
            await db.commit()
            results["old_webhook_deliveries"] = _affected_rows(r)

            return results

    return run_async(_run())
