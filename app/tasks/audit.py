from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from app.core.database import run_async
from app.core.logging import get_logger
from app.workers.celery_app import celery_app

logger = get_logger("app.tasks.audit")


@celery_app.task(name="app.tasks.audit.log_event")
def log_audit_event_task(
    user_id: str | None,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    success: bool = True,
    reason: str | None = None,
    previous_value: dict[str, Any] | None = None,
    new_value: dict[str, Any] | None = None,
) -> str:
    async def _run() -> str:
        from app.admin.models import AdminAuditLog
        from sqlalchemy.ext.asyncio import AsyncSession

        from app.core.database import async_session_factory

        async with async_session_factory() as db:
            entry = AdminAuditLog(
                admin_user_id=None,
                user_id=uuid.UUID(user_id) if user_id else None,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                previous_value=previous_value,
                new_value=new_value,
                ip_address=ip_address,
                user_agent=user_agent,
                reason=reason,
                success=success,
            )
            db.add(entry)
            await db.commit()
            return str(entry.id)

    return run_async(_run())


@celery_app.task(name="app.tasks.audit.log_admin_action")
def log_admin_action_task(
    admin_user_id: str,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    success: bool = True,
    reason: str | None = None,
    previous_value: dict[str, Any] | None = None,
    new_value: dict[str, Any] | None = None,
    user_id: str | None = None,
) -> str:
    async def _run() -> str:
        from app.admin.models import AdminAuditLog
        from app.core.database import async_session_factory

        async with async_session_factory() as db:
            entry = AdminAuditLog(
                admin_user_id=uuid.UUID(admin_user_id),
                user_id=uuid.UUID(user_id) if user_id else None,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                previous_value=previous_value,
                new_value=new_value,
                ip_address=ip_address,
                user_agent=user_agent,
                reason=reason,
                success=success,
            )
            db.add(entry)
            await db.commit()
            return str(entry.id)

    return run_async(_run())


@celery_app.task(name="app.tasks.audit.log_runtime_action")
def log_runtime_action_task(
    runtime_id: str,
    action: str,
    user_id: str | None = None,
    organization_id: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    success: bool = True,
    error_message: str | None = None,
) -> str:
    async def _run() -> str:
        from app.admin.services.audit_log import AuditLogService
        from app.core.database import async_session_factory

        async with async_session_factory() as db:
            service = AuditLogService(db)
            entry = await service.log(
                admin_id="system",
                action=f"runtime.{action}",
                resource_type="runtime",
                resource_id=runtime_id,
                user_id=user_id,
                ip_address=ip_address,
                user_agent=user_agent,
                success=success,
                reason=error_message,
                new_value={"organization_id": organization_id} if organization_id else {},
            )
            await db.commit()
            return str(entry.id)

    return run_async(_run())


@celery_app.task(name="app.tasks.audit.log_billing_action")
def log_billing_action_task(
    user_id: str,
    action: str,
    amount: str | None = None,
    currency: str | None = None,
    ip_address: str | None = None,
    success: bool = True,
    error_message: str | None = None,
) -> str:
    async def _run() -> str:
        from app.admin.services.audit_log import AuditLogService
        from app.core.database import async_session_factory

        async with async_session_factory() as db:
            service = AuditLogService(db)
            entry = await service.log(
                admin_id="system",
                action=f"billing.{action}",
                resource_type="billing",
                user_id=user_id,
                ip_address=ip_address,
                success=success,
                reason=error_message,
                new_value={"amount": amount, "currency": currency} if amount else {},
            )
            await db.commit()
            return str(entry.id)

    return run_async(_run())
