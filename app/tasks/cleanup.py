from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.database import run_async
from app.core.logging import get_logger
from app.workers.celery_app import celery_app

logger = get_logger("app.tasks.cleanup")


@celery_app.task(name="app.tasks.cleanup.expired_sessions")
def cleanup_expired_sessions_task() -> int:
    async def _run() -> int:
        from app.core.database import async_session_factory
        from app.models.sessions import Session
        from sqlalchemy import delete

        async with async_session_factory() as db:
            now = datetime.now(UTC)
            result = await db.execute(
                delete(Session).where(Session.expires_at < now)
            )
            await db.commit()
            count = result.rowcount
            logger.info("Cleaned expired sessions", extra={"count": count})
            return count

    return run_async(_run())


@celery_app.task(name="app.tasks.cleanup.expired_refresh_tokens")
def cleanup_expired_refresh_tokens_task() -> int:
    async def _run() -> int:
        from app.core.database import async_session_factory
        from app.models.refresh_tokens import RefreshToken
        from sqlalchemy import delete

        async with async_session_factory() as db:
            now = datetime.now(UTC)
            result = await db.execute(
                delete(RefreshToken).where(RefreshToken.expires_at < now)
            )
            await db.commit()
            count = result.rowcount
            logger.info("Cleaned expired refresh tokens", extra={"count": count})
            return count

    return run_async(_run())


@celery_app.task(name="app.tasks.cleanup.revoked_tokens")
def cleanup_revoked_tokens_task() -> int:
    async def _run() -> int:
        from app.core.database import async_session_factory
        from app.models.sessions import Session
        from app.models.refresh_tokens import RefreshToken
        from sqlalchemy import delete

        async with async_session_factory() as db:
            cutoff = datetime.now(UTC) - timedelta(days=30)
            session_result = await db.execute(
                delete(Session).where(Session.revoked == True, Session.created_at < cutoff)
            )
            token_result = await db.execute(
                delete(RefreshToken).where(RefreshToken.revoked == True, RefreshToken.created_at < cutoff)
            )
            await db.commit()
            total = session_result.rowcount + token_result.rowcount
            logger.info("Cleaned revoked tokens", extra={"sessions_deleted": session_result.rowcount, "tokens_deleted": token_result.rowcount})
            return total

    return run_async(_run())


@celery_app.task(name="app.tasks.cleanup.old_request_logs")
def cleanup_old_request_logs_task(older_than_days: int = 90) -> int:
    async def _run() -> int:
        from app.core.database import async_session_factory
        from app.models.request_logs import RequestLog
        from sqlalchemy import delete

        async with async_session_factory() as db:
            cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
            result = await db.execute(delete(RequestLog).where(RequestLog.created_at < cutoff))
            await db.commit()
            count = result.rowcount
            logger.info("Cleaned old request logs", extra={"count": count, "older_than_days": older_than_days})
            return count

    return run_async(_run())


@celery_app.task(name="app.tasks.cleanup.old_build_artifacts")
def cleanup_old_build_artifacts_task(older_than_days: int = 7) -> int:
    async def _run() -> int:
        from app.core.database import async_session_factory
        from app.models.runtimes import RuntimeBuildChunk
        from sqlalchemy import delete

        async with async_session_factory() as db:
            cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
            result = await db.execute(
                delete(RuntimeBuildChunk).where(
                    RuntimeBuildChunk.runtime_id.is_(None),
                    RuntimeBuildChunk.created_at < cutoff,
                )
            )
            await db.commit()
            count = result.rowcount
            logger.info("Cleaned old build artifacts", extra={"count": count, "older_than_days": older_than_days})
            return count

    return run_async(_run())


@celery_app.task(name="app.tasks.cleanup.expired_embedding_cache")
def cleanup_expired_embedding_cache_task() -> int:
    async def _run() -> int:
        from app.core.database import async_session_factory
        from app.models.embedding_cache import EmbeddingCache
        from sqlalchemy import delete

        async with async_session_factory() as db:
            now = datetime.now(UTC)
            result = await db.execute(
                delete(EmbeddingCache).where(
                    EmbeddingCache.expires_at.is_not(None),
                    EmbeddingCache.expires_at < now,
                )
            )
            await db.commit()
            count = result.rowcount
            logger.info("Cleaned expired embedding cache", extra={"count": count})
            return count

    return run_async(_run())


@celery_app.task(name="app.tasks.cleanup.old_audit_logs")
def cleanup_old_audit_logs_task(older_than_days: int = 365) -> int:
    async def _run() -> int:
        from app.core.database import async_session_factory
        from app.admin.models import AdminAuditLog
        from sqlalchemy import delete

        async with async_session_factory() as db:
            cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
            result = await db.execute(
                delete(AdminAuditLog).where(AdminAuditLog.created_at < cutoff)
            )
            await db.commit()
            count = result.rowcount
            logger.info("Cleaned old audit logs", extra={"count": count, "older_than_days": older_than_days})
            return count

    return run_async(_run())


@celery_app.task(name="app.tasks.cleanup.old_webhook_deliveries")
def cleanup_old_webhook_deliveries_task(older_than_days: int = 30) -> int:
    async def _run() -> int:
        from app.core.database import async_session_factory
        from app.models.webhook_deliveries import WebhookDelivery
        from sqlalchemy import delete

        async with async_session_factory() as db:
            cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
            result = await db.execute(
                delete(WebhookDelivery).where(WebhookDelivery.created_at < cutoff)
            )
            await db.commit()
            count = result.rowcount
            logger.info("Cleaned old webhook deliveries", extra={"count": count, "older_than_days": older_than_days})
            return count

    return run_async(_run())


@celery_app.task(name="app.tasks.cleanup.daily_cleanup")
def daily_cleanup_task() -> dict[str, int]:
    async def _run() -> dict[str, int]:
        from app.core.database import async_session_factory
        from app.models.sessions import Session
        from app.models.refresh_tokens import RefreshToken
        from app.admin.models import AdminAuditLog
        from app.models.webhook_deliveries import WebhookDelivery
        from sqlalchemy import delete

        async with async_session_factory() as db:
            results: dict[str, int] = {}

            now = datetime.now(UTC)
            r = await db.execute(delete(Session).where(Session.expires_at < now))
            await db.commit()
            results["expired_sessions"] = r.rowcount

            r = await db.execute(delete(RefreshToken).where(RefreshToken.expires_at < now))
            await db.commit()
            results["expired_refresh_tokens"] = r.rowcount

            r = await db.execute(delete(AdminAuditLog).where(AdminAuditLog.created_at < datetime.now(UTC) - timedelta(days=365)))
            await db.commit()
            results["old_audit_logs"] = r.rowcount

            r = await db.execute(delete(WebhookDelivery).where(WebhookDelivery.created_at < datetime.now(UTC) - timedelta(days=30)))
            await db.commit()
            results["old_webhook_deliveries"] = r.rowcount

            return results

    return run_async(_run())
