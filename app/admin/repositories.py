from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.admin.constants import AlertStatus
from app.admin.models import (
    AdminAuditLog,
    AdminEvent,
    AdminEventTimeline,
    AdminSession,
    AdminUser,
    FeatureFlag,
    IPAllowList,
    IPRecord,
    LoginEvent,
    NotificationConfig,
    OrganizationLock,
    SecurityAlert,
    UserFingerprint,
    WalletFreeze,
)
from app.repositories.base import BaseRepository


class AdminUserRepository(BaseRepository[AdminUser]):
    async def get_by_user_id(self, user_id: uuid.UUID) -> AdminUser | None:
        result = await self.db.execute(select(AdminUser).where(AdminUser.user_id == user_id))
        return result.scalar_one_or_none()

    async def get_by_id(self, admin_id: uuid.UUID) -> AdminUser | None:
        return await self.get(admin_id)

    async def list_all(self, limit: int = 50, offset: int = 0, role: str | None = None) -> list[AdminUser]:
        stmt = select(AdminUser)
        if role:
            stmt = stmt.where(AdminUser.role == role)
        stmt = stmt.limit(limit).offset(offset)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())


class AdminSessionRepository(BaseRepository[AdminSession]):
    async def get_by_token_hash(self, token_hash: str) -> AdminSession | None:
        result = await self.db.execute(select(AdminSession).where(AdminSession.token_hash == token_hash))
        return result.scalar_one_or_none()

    async def revoke_for_user(self, admin_user_id: uuid.UUID) -> None:
        result = await self.db.execute(select(AdminSession).where(AdminSession.admin_user_id == admin_user_id))
        sessions = result.scalars().all()
        for session in sessions:
            session.revoked = True
        await self.db.flush()


class AdminAuditLogRepository(BaseRepository[AdminAuditLog]):
    async def list_all(
        self,
        limit: int = 50,
        offset: int = 0,
        action: str | None = None,
        admin_user_id: uuid.UUID | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[AdminAuditLog]:
        stmt = select(AdminAuditLog).order_by(AdminAuditLog.id.desc())
        if action:
            stmt = stmt.where(AdminAuditLog.action == action)
        if admin_user_id:
            stmt = stmt.where(AdminAuditLog.admin_user_id == admin_user_id)
        if date_from:
            stmt = stmt.where(AdminAuditLog.created_at >= date_from)
        if date_to:
            stmt = stmt.where(AdminAuditLog.created_at <= date_to)
        stmt = stmt.limit(limit).offset(offset)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())


class IPAllowListRepository(BaseRepository[IPAllowList]):
    async def list_active(self) -> list[IPAllowList]:
        result = await self.db.execute(select(IPAllowList).where(IPAllowList.is_active == True))
        return list(result.scalars().all())

    async def get_by_ip(self, ip_address: str) -> IPAllowList | None:
        result = await self.db.execute(select(IPAllowList).where(IPAllowList.ip_address == ip_address))
        return result.scalar_one_or_none()


class IPRecordRepository(BaseRepository[IPRecord]):
    async def get_by_ip(self, ip_address: str) -> IPRecord | None:
        result = await self.db.execute(select(IPRecord).where(IPRecord.ip_address == ip_address))
        return result.scalar_one_or_none()

    async def update_request_count(self, ip_address: str, success: bool, record: IPRecord | None = None) -> IPRecord:
        if record is None:
            record = await self.get_by_ip(ip_address)
        if record is None:
            record = IPRecord(ip_address=ip_address)
            self.db.add(record)
            await self.db.flush()
        record.total_requests += 1
        if not success:
            record.failed_requests += 1
        record.last_seen = datetime.now(UTC)
        await self.db.flush()
        return record

    async def update_risk_score(self, ip_address: str, score: int, record: IPRecord | None = None) -> IPRecord:
        if record is None:
            record = await self.get_by_ip(ip_address)
        if record is None:
            record = IPRecord(ip_address=ip_address)
            self.db.add(record)
            await self.db.flush()
        record.risk_score = min(100, max(0, score))
        await self.db.flush()
        return record

    async def ban_ip(self, ip_address: str, ban_type: str, reason: str | None, duration_hours: int | None, record: IPRecord | None = None) -> IPRecord:
        if record is None:
            record = await self.get_by_ip(ip_address)
        if record is None:
            record = IPRecord(ip_address=ip_address)
            self.db.add(record)
            await self.db.flush()
        record.is_banned = True
        record.ban_type = ban_type
        record.ban_reason = reason
        if ban_type == "temporary" and duration_hours:
            record.ban_expires_at = datetime.now(UTC) + timedelta(hours=duration_hours)
        await self.db.flush()
        return record

    async def unban_ip(self, ip_address: str, record: IPRecord | None = None) -> IPRecord | None:
        if record is None:
            record = await self.get_by_ip(ip_address)
        if record:
            record.is_banned = False
            record.ban_type = None
            record.ban_reason = None
            record.ban_expires_at = None
            await self.db.flush()
        return record

    async def is_banned(self, ip_address: str) -> bool:
        result = await self.db.execute(select(IPRecord).where(IPRecord.ip_address == ip_address, IPRecord.is_banned == True))
        record = result.scalar_one_or_none()
        if record is None:
            return False
        if record.ban_type == "permanent":
            return True
        if record.ban_expires_at and record.ban_expires_at > datetime.now(UTC):
            return True
        return False

    async def list_banned(self, limit: int = 50, offset: int = 0) -> list[IPRecord]:
        result = await self.db.execute(select(IPRecord).where(IPRecord.is_banned == True).limit(limit).offset(offset))
        return list(result.scalars().all())

    async def list_by_risk(self, min_score: int = 70, limit: int = 50, offset: int = 0) -> list[IPRecord]:
        result = await self.db.execute(select(IPRecord).where(IPRecord.risk_score >= min_score).order_by(IPRecord.risk_score.desc()).limit(limit).offset(offset))
        return list(result.scalars().all())


class UserFingerprintRepository(BaseRepository[UserFingerprint]):
    async def get_by_hash(self, fingerprint_hash: str) -> UserFingerprint | None:
        result = await self.db.execute(select(UserFingerprint).where(UserFingerprint.fingerprint_hash == fingerprint_hash))
        return result.scalar_one_or_none()

    async def list_by_user(self, user_id: uuid.UUID, limit: int = 50, offset: int = 0) -> list[UserFingerprint]:
        result = await self.db.execute(select(UserFingerprint).where(UserFingerprint.user_id == user_id).limit(limit).offset(offset))
        return list(result.scalars().all())

    async def list_flagged(self, min_risk: int = 50, limit: int = 50, offset: int = 0) -> list[UserFingerprint]:
        result = await self.db.execute(select(UserFingerprint).where(UserFingerprint.risk_score >= min_risk).order_by(UserFingerprint.risk_score.desc()).limit(limit).offset(offset))
        return list(result.scalars().all())


class LoginEventRepository(BaseRepository[LoginEvent]):
    async def get_failures_by_ip(self, ip_address: str, hours: int = 1) -> int:
        since = datetime.now(UTC) - timedelta(hours=hours)
        result = await self.db.execute(select(func.count()).select_from(LoginEvent).where(LoginEvent.ip_address == ip_address, LoginEvent.success == False, LoginEvent.created_at >= since))
        return result.scalar() or 0

    async def get_failures_by_user(self, user_id: uuid.UUID, hours: int = 1) -> int:
        since = datetime.now(UTC) - timedelta(hours=hours)
        result = await self.db.execute(select(func.count()).select_from(LoginEvent).where(LoginEvent.user_id == user_id, LoginEvent.success == False, LoginEvent.created_at >= since))
        return result.scalar() or 0

    async def get_events_by_ip(self, ip_address: str, limit: int = 50, offset: int = 0) -> list[LoginEvent]:
        result = await self.db.execute(select(LoginEvent).where(LoginEvent.ip_address == ip_address).order_by(LoginEvent.created_at.desc()).limit(limit).offset(offset))
        return list(result.scalars().all())


class SecurityAlertRepository(BaseRepository[SecurityAlert]):
    async def list_all(
        self,
        limit: int = 50,
        offset: int = 0,
        status: str | None = None,
        risk_level: str | None = None,
        alert_type: str | None = None,
        min_score: int | None = None,
        max_score: int | None = None,
        organization_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        ip_address: str | None = None,
    ) -> list[SecurityAlert]:
        stmt = select(SecurityAlert).order_by(SecurityAlert.risk_score.desc())
        if status:
            stmt = stmt.where(SecurityAlert.status == status)
        if risk_level:
            stmt = stmt.where(SecurityAlert.risk_level == risk_level)
        if alert_type:
            stmt = stmt.where(SecurityAlert.alert_type == alert_type)
        if min_score is not None:
            stmt = stmt.where(SecurityAlert.risk_score >= min_score)
        if max_score is not None:
            stmt = stmt.where(SecurityAlert.risk_score <= max_score)
        if organization_id:
            stmt = stmt.where(SecurityAlert.organization_id == organization_id)
        if user_id:
            stmt = stmt.where(SecurityAlert.user_id == user_id)
        if ip_address:
            stmt = stmt.where(SecurityAlert.ip_address == ip_address)
        stmt = stmt.limit(limit).offset(offset)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_open_count(self) -> int:
        result = await self.db.execute(select(func.count()).select_from(SecurityAlert).where(SecurityAlert.status == AlertStatus.OPEN))
        return result.scalar() or 0

    async def update_status(self, alert_id: uuid.UUID, status: str, acknowledged_by: uuid.UUID | None = None) -> SecurityAlert | None:
        result = await self.db.execute(select(SecurityAlert).where(SecurityAlert.id == alert_id))
        alert = result.scalar_one_or_none()
        if alert:
            alert.status = status
            if acknowledged_by and status == AlertStatus.ACKNOWLEDGED:
                alert.acknowledged_by = acknowledged_by
            if status == AlertStatus.RESOLVED:
                alert.resolved_at = datetime.now(UTC)
            await self.db.flush()
        return alert


class FeatureFlagRepository(BaseRepository[FeatureFlag]):
    async def get_by_key(self, key: str) -> FeatureFlag | None:
        result = await self.db.execute(select(FeatureFlag).where(FeatureFlag.key == key))
        return result.scalar_one_or_none()

    async def list_all(self, scope: str | None = None, enabled_only: bool = False, limit: int = 50, offset: int = 0) -> list[FeatureFlag]:
        stmt = select(FeatureFlag)
        if scope:
            stmt = stmt.where(FeatureFlag.scope == scope)
        if enabled_only:
            stmt = stmt.where(FeatureFlag.enabled == True)
        stmt = stmt.limit(limit).offset(offset)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())


class NotificationConfigRepository(BaseRepository[NotificationConfig]):
    async def list_all(self, event_type: str | None = None, is_enabled: bool | None = None, limit: int = 50, offset: int = 0) -> list[NotificationConfig]:
        stmt = select(NotificationConfig)
        if event_type:
            stmt = stmt.where(NotificationConfig.event_type == event_type)
        if is_enabled is not None:
            stmt = stmt.where(NotificationConfig.is_enabled == is_enabled)
        stmt = stmt.limit(limit).offset(offset)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())


class AdminEventRepository(BaseRepository[AdminEvent]):
    async def list_unread(self, limit: int = 50, offset: int = 0) -> list[AdminEvent]:
        result = await self.db.execute(select(AdminEvent).where(AdminEvent.is_read == False).order_by(AdminEvent.created_at.desc()).limit(limit).offset(offset))
        return list(result.scalars().all())

    async def list_all(
        self,
        limit: int = 50,
        offset: int = 0,
        category: str | None = None,
        unread_only: bool = False,
    ) -> list[AdminEvent]:
        stmt = select(AdminEvent).order_by(AdminEvent.created_at.desc())
        if category:
            stmt = stmt.where(AdminEvent.category == category)
        if unread_only:
            stmt = stmt.where(AdminEvent.is_read == False)
        stmt = stmt.limit(limit).offset(offset)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())


class WalletFreezeRepository(BaseRepository[WalletFreeze]):
    async def get_active_by_user(self, user_id: uuid.UUID) -> WalletFreeze | None:
        result = await self.db.execute(select(WalletFreeze).where(WalletFreeze.user_id == user_id, WalletFreeze.is_frozen == True))
        return result.scalar_one_or_none()

    async def is_frozen(self, user_id: uuid.UUID) -> bool:
        freeze = await self.get_active_by_user(user_id)
        return freeze is not None


class OrganizationLockRepository(BaseRepository[OrganizationLock]):
    async def get_active_by_org(self, organization_id: uuid.UUID) -> OrganizationLock | None:
        result = await self.db.execute(select(OrganizationLock).where(OrganizationLock.organization_id == organization_id, OrganizationLock.is_locked == True))
        return result.scalar_one_or_none()

    async def is_locked(self, organization_id: uuid.UUID) -> bool:
        lock = await self.get_active_by_org(organization_id)
        return lock is not None


class AdminEventTimelineRepository(BaseRepository[AdminEventTimeline]):
    async def list_by_request_id(self, request_id: str) -> list[AdminEventTimeline]:
        result = await self.db.execute(select(AdminEventTimeline).where(AdminEventTimeline.request_id == request_id).order_by(AdminEventTimeline.sequence))
        return list(result.scalars().all())

    async def list_all(
        self,
        limit: int = 50,
        offset: int = 0,
        organization_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        runtime_id: uuid.UUID | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        event_type: str | None = None,
    ) -> list[AdminEventTimeline]:
        stmt = select(AdminEventTimeline).order_by(AdminEventTimeline.created_at.desc())
        if organization_id:
            stmt = stmt.where(AdminEventTimeline.organization_id == organization_id)
        if user_id:
            stmt = stmt.where(AdminEventTimeline.user_id == user_id)
        if runtime_id:
            stmt = stmt.where(AdminEventTimeline.runtime_id == runtime_id)
        if event_type:
            stmt = stmt.where(AdminEventTimeline.event_type == event_type)
        if date_from:
            stmt = stmt.where(AdminEventTimeline.created_at >= date_from)
        if date_to:
            stmt = stmt.where(AdminEventTimeline.created_at <= date_to)
        stmt = stmt.limit(limit).offset(offset)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
