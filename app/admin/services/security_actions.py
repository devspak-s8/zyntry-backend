from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.constants import AlertActionType, AlertStatus
from app.admin.models import SecurityAlert
from app.admin.repositories import SecurityAlertRepository


class SecurityActionsService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._repo = SecurityAlertRepository(db)

    async def block_ip(self, ip_address: str, reason: str | None = None) -> bool:
        from app.admin.repositories import IPRecordRepository
        repo = IPRecordRepository(self.db)
        await repo.ban_ip(ip_address, ban_type="permanent", reason=reason, duration_hours=None)
        return True

    async def block_fingerprint(self, fingerprint_hash: str, reason: str | None = None) -> bool:
        from app.admin.repositories import UserFingerprintRepository
        repo = UserFingerprintRepository(self.db)
        record = await repo.get_by_hash(fingerprint_hash)
        if record:
            record.risk_score = 100
            await self.db.flush()
        return True

    async def suspend_user(self, user_id: str, reason: str | None = None) -> bool:
        from app.models.users import User
        result = await self.db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user:
            user.is_active = False
            await self.db.flush()
        return True

    async def disable_api_key(self, api_key_id: str, reason: str | None = None) -> bool:
        from app.models.apikeys import ApiKey
        result = await self.db.execute(select(ApiKey).where(ApiKey.id == api_key_id))
        key = result.scalar_one_or_none()
        if key:
            key.is_active = False
            await self.db.flush()
        return True

    async def freeze_wallet(self, user_id: str, reason: str | None = None) -> bool:
        from app.admin.models import WalletFreeze
        from app.models.billing import Wallet
        result = await self.db.execute(select(Wallet).where(Wallet.user_id == user_id))
        wallet = result.scalar_one_or_none()
        if wallet:
            freeze = WalletFreeze(user_id=user_id, wallet_id=wallet.id, reason=reason or "Admin freeze")
            self.db.add(freeze)
            await self.db.flush()
        return True

    async def lock_organization(self, organization_id: str, reason: str | None = None) -> bool:
        from app.admin.models import OrganizationLock
        from app.models.organizations import Organization
        result = await self.db.execute(select(Organization).where(Organization.id == organization_id))
        org = result.scalar_one_or_none()
        if org:
            lock = OrganizationLock(organization_id=organization_id, reason=reason or "Admin lock")
            self.db.add(lock)
            await self.db.flush()
        return True

    async def require_mfa(self, admin_id: str, reason: str | None = None) -> bool:
        from app.admin.models import AdminUser
        result = await self.db.execute(select(AdminUser).where(AdminUser.id == admin_id))
        admin_user = result.scalar_one_or_none()
        if admin_user:
            admin_user.mfa_enabled = True
            await self.db.flush()
        return True

    async def clear_alert(self, alert_id: str) -> bool:
        return bool(await self._repo.update_status(alert_id, AlertStatus.RESOLVED))

    async def apply_action(self, alert_id: str, action: str, reason: str | None = None) -> dict[str, Any]:
        alert = await self._repo.get_by_id(alert_id)
        if alert is None:
            return {"success": False, "error": "Alert not found"}

        result = {"success": True, "action": action, "alert_id": alert_id}

        if action == AlertActionType.BLOCK_IP.value and alert.ip_address:
            await self.block_ip(alert.ip_address, reason)
        elif action == AlertActionType.BLOCK_FINGERPRINT.value and alert.fingerprint_hash:
            await self.block_fingerprint(alert.fingerprint_hash, reason)
        elif action == AlertActionType.SUSPEND_USER.value and alert.user_id:
            await self.suspend_user(str(alert.user_id), reason)
        elif action == AlertActionType.DISABLE_API_KEY.value:
            pass
        elif action == AlertActionType.FREEZE_WALLET.value and alert.user_id:
            await self.freeze_wallet(str(alert.user_id), reason)
        elif action == AlertActionType.LOCK_ORGANIZATION.value and alert.organization_id:
            await self.lock_organization(str(alert.organization_id), reason)
        elif action == AlertActionType.REQUIRE_MFA.value and alert.user_id:
            pass
        elif action == AlertActionType.CLEAR_ALERT.value:
            await self.clear_alert(alert_id)

        return result

    async def list_pending_actions(self, limit: int = 50, offset: int = 0) -> list[SecurityAlert]:
        return await self._repo.list_all(limit=limit, offset=offset, status=AlertStatus.OPEN.value)