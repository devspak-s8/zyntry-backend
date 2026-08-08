from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.models import AdminAuditLog
from app.admin.repositories import AdminAuditLogRepository


class AuditLogService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._repo = AdminAuditLogRepository(db)

    async def log_action(
        self,
        admin_user_id: str,
        action: str,
        resource_type: str,
        resource_id: str | None,
        previous_value: dict[str, Any] | None,
        new_value: dict[str, Any] | None,
        ip_address: str | None,
        user_agent: str | None,
        reason: str | None,
        success: bool = True,
        user_id: str | None = None,
    ) -> AdminAuditLog:
        entry = AdminAuditLog(
            admin_user_id=admin_user_id,
            user_id=user_id,
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
        self.db.add(entry)
        await self.db.flush()
        return entry

    async def log(
        self,
        admin_id: str,
        action: str,
        resource_type: str,
        **kwargs: Any,
    ) -> AdminAuditLog:
        return await self.log_action(
            admin_user_id=admin_id,
            action=action,
            resource_type=resource_type,
            resource_id=kwargs.get("resource_id"),
            previous_value=kwargs.get("previous_value"),
            new_value=kwargs.get("new_value"),
            ip_address=kwargs.get("ip_address"),
            user_agent=kwargs.get("user_agent"),
            reason=kwargs.get("reason"),
            success=kwargs.get("success", True),
            user_id=kwargs.get("user_id"),
        )