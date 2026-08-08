from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.database import run_async
from app.core.logging import get_logger
from app.workers.celery_app import celery_app

logger = get_logger("app.tasks.security")


@celery_app.task(name="app.tasks.security.run_security_scan")
def run_security_scan_task() -> dict[str, Any]:
    async def _run() -> dict[str, Any]:
        from app.admin.repositories import (
            LoginEventRepository,
            SecurityAlertRepository,
            IPRecordRepository,
        )
        from app.admin.services.notifications import AdminNotificationService
        from app.core.database import async_session_factory
        from sqlalchemy import select
        from app.admin.models import LoginEvent, IPRecord

        async with async_session_factory() as db:
            ip_repo = IPRecordRepository(db)
            login_repo = LoginEventRepository(db)
            alert_repo = SecurityAlertRepository(db)
            notify = AdminNotificationService(db)

            since = datetime.now(UTC) - timedelta(hours=1)
            result = await db.execute(
                select(LoginEvent.ip_address)
                .where(LoginEvent.created_at >= since, LoginEvent.success == False)
                .distinct()
            )
            suspicious_ips = [r[0] for r in result.scalars().all() if r[0]]

            alerts_created = 0
            for ip_address in suspicious_ips:
                record = await ip_repo.get_by_ip(ip_address)
                failed_count = await login_repo.get_failures_by_ip(ip_address, hours=1)

                if failed_count >= 5:
                    existing = await db.execute(
                        select(SecurityAlert).where(
                            SecurityAlert.ip_address == ip_address,
                            SecurityAlert.alert_type == "brute_force",
                            SecurityAlert.status == "open",
                        )
                    )
                    if existing.scalar_one_or_none() is None:
                        risk_score = min(100, 30 + failed_count * 5)
                        from app.admin.constants import risk_level_from_score
                        risk_level = risk_level_from_score(risk_score).value
                        alert = await alert_repo.create(
                            alert_type="brute_force",
                            risk_score=risk_score,
                            risk_level=risk_level,
                            title=f"Brute force detected from {ip_address}",
                            description=f"{failed_count} failed logins in the last hour",
                            ip_address=ip_address,
                            triggered_rules=["brute_force"],
                        )
                        await notify.alert_generated(alert)
                        await ip_repo.ban_ip(ip_address, "temporary", "Brute force detected", 24)
                        alerts_created += 1
                        logger.warning("Brute force detected", extra={"ip_address": ip_address, "failed_count": failed_count})

            return {"suspicious_ips": len(suspicious_ips), "alerts_created": alerts_created}

    return run_async(_run())


@celery_app.task(name="app.tasks.security.analyze_ip")
def analyze_ip_task(ip_address: str) -> dict[str, Any]:
    async def _run() -> dict[str, Any]:
        from sqlalchemy import update as sql_update
        from app.admin.repositories import IPRecordRepository
        from app.admin.services.security_engine import SecurityEngine
        from app.core.database import async_session_factory
        from app.admin.models import IPRecord

        async with async_session_factory() as db:
            engine = SecurityEngine(db)
            record = await engine.enrich_ip_record(ip_address)
            risk_score = await engine.calculate_risk_score(
                threat_types=[],
                ip_address=ip_address,
                user_id=None,
                organization_id=None,
                is_vpn=record.is_vpn,
                is_proxy=record.is_proxy,
                is_tor=record.is_tor,
                failed_auth_count=record.failed_requests,
                request_rate=record.total_requests,
            )
            await db.execute(
                sql_update(IPRecord)
                .where(IPRecord.ip_address == ip_address)
                .values(risk_score=risk_score)
            )
            await db.commit()
            return {"ip_address": ip_address, "risk_score": risk_score, "record_id": str(record.id)}

    return run_async(_run())


@celery_app.task(name="app.tasks.security.detect_api_abuse")
def detect_api_abuse_task(api_key_id: str, threshold: int = 1000, time_window_hours: int = 1) -> dict[str, Any]:
    async def _run() -> dict[str, Any]:
        from app.admin.services.security_engine import SecurityEngine
        from app.core.database import async_session_factory
        from app.models.apikeys import ApiKey
        from sqlalchemy import select

        async with async_session_factory() as db:
            engine = SecurityEngine(db)
            result = await db.execute(select(ApiKey).where(ApiKey.id == uuid.UUID(api_key_id)))
            api_key = result.scalar_one_or_none()
            if not api_key:
                return {"detected": False, "reason": "API key not found"}

            analysis = await engine.check_api_abuse(api_key_id, time_window=time_window_hours * 3600, threshold=threshold)
            if analysis["detected"]:
                await engine.generate_alert(
                    alert_type="api_abuse",
                    risk_score=40,
                    title=f"API abuse detected for key {api_key.name}",
                    description=f"{analysis['count']} requests in the last hour",
                    ip_address=None,
                    organization_id=str(api_key.organization_id),
                    user_id=str(api_key.user_id) if api_key.user_id else None,
                    fingerprint_hash=None,
                    triggered_rules=["api_abuse"],
                    metadata={"threshold": threshold, "count": analysis["count"]},
                )
            return analysis

    return run_async(_run())


@celery_app.task(name="app.tasks.security.detect_wallet_abuse")
def detect_wallet_abuse_task(user_id: str, threshold: int = 5, time_window_hours: int = 1) -> dict[str, Any]:
    async def _run() -> dict[str, Any]:
        from app.admin.services.security_engine import SecurityEngine
        from app.core.database import async_session_factory

        async with async_session_factory() as db:
            engine = SecurityEngine(db)
            analysis = await engine.check_wallet_abuse(user_id, time_window=time_window_hours * 3600, threshold=threshold)
            if analysis["detected"]:
                await engine.generate_alert(
                    alert_type="wallet_abuse",
                    risk_score=50,
                    title=f"Wallet abuse detected for user {user_id}",
                    description=f"{analysis.get('count', 0)} wallet actions in the last hour",
                    ip_address=None,
                    organization_id=None,
                    user_id=user_id,
                    fingerprint_hash=None,
                    triggered_rules=["wallet_abuse"],
                    metadata={"threshold": threshold},
                )
            return analysis

    return run_async(_run())


@celery_app.task(name="app.tasks.security.ban_ip")
def ban_ip_task(ip_address: str, ban_type: str = "temporary", reason: str | None = None, duration_hours: int | None = 24) -> bool:
    async def _run() -> bool:
        from app.admin.repositories import IPRecordRepository
        from app.core.database import async_session_factory

        async with async_session_factory() as db:
            ip_repo = IPRecordRepository(db)
            await ip_repo.ban_ip(ip_address, ban_type, reason, duration_hours)
            await db.commit()
            logger.info("IP banned", extra={"ip_address": ip_address, "ban_type": ban_type, "reason": reason})
            return True

    return run_async(_run())


@celery_app.task(name="app.tasks.security.blacklist_ip")
def blacklist_ip_task(ip_address: str, reason: str | None = None) -> bool:
    async def _run() -> bool:
        from app.admin.repositories import IPRecordRepository
        from app.core.database import async_session_factory

        async with async_session_factory() as db:
            ip_repo = IPRecordRepository(db)
            record = await ip_repo.get_by_ip(ip_address)
            if record:
                record.is_banned = True
                record.ban_type = "permanent"
                record.ban_reason = reason
                await db.commit()
            return record is not None

    return run_async(_run())


@celery_app.task(name="app.tasks.security.unban_ip")
def unban_ip_task(ip_address: str) -> bool:
    async def _run() -> bool:
        from app.admin.repositories import IPRecordRepository
        from app.core.database import async_session_factory

        async with async_session_factory() as db:
            ip_repo = IPRecordRepository(db)
            await ip_repo.unban_ip(ip_address)
            await db.commit()
            return True

    return run_async(_run())


@celery_app.task(name="app.tasks.security.expire_bans")
def expire_bans_task() -> int:
    async def _run() -> int:
        from app.core.database import async_session_factory
        from app.admin.models import IPRecord
        from sqlalchemy import update as sql_update

        async with async_session_factory() as db:
            now = datetime.now(UTC)
            result = await db.execute(
                sql_update(IPRecord)
                .where(
                    IPRecord.is_banned == True,
                    IPRecord.ban_type == "temporary",
                    IPRecord.ban_expires_at <= now,
                )
                .values(is_banned=False, ban_type=None, ban_reason=None, ban_expires_at=None)
            )
            await db.commit()
            count = result.rowcount
            logger.info("Expired temporary IP bans", extra={"count": count})
            return count

    return run_async(_run())
