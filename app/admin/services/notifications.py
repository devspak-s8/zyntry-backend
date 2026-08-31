from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.models import AdminEvent, NotificationConfig, SecurityAlert
from app.admin.repositories import NotificationConfigRepository


class AdminNotificationService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._repo = NotificationConfigRepository(db)

    async def list_configs(self, event_type: str | None = None, is_enabled: bool | None = None, limit: int = 50, offset: int = 0) -> list[NotificationConfig]:
        return await self._repo.list_all(event_type=event_type, is_enabled=is_enabled, limit=limit, offset=offset)

    async def get_config(self, config_id: str) -> NotificationConfig | None:
        result = await self.db.execute(select(NotificationConfig).where(NotificationConfig.id == config_id))
        return result.scalar_one_or_none()

    async def create_config(self, event_type: str, provider_type: str, name: str, is_enabled: bool = True, config: dict[str, Any] | None = None) -> NotificationConfig:
        nc = NotificationConfig(
            event_type=event_type,
            provider_type=provider_type,
            name=name,
            is_enabled=is_enabled,
            config=config,
        )
        self.db.add(nc)
        await self.db.flush()
        return nc

    async def update_config(self, config_id: str, **kwargs: Any) -> NotificationConfig | None:
        nc = await self.get_config(config_id)
        if nc is None:
            return None
        for k, v in kwargs.items():
            if hasattr(nc, k):
                setattr(nc, k, v)
        await self.db.flush()
        return nc

    async def enable_config(self, config_id: str) -> NotificationConfig | None:
        return await self.update_config(config_id, is_enabled=True)

    async def disable_config(self, config_id: str) -> NotificationConfig | None:
        return await self.update_config(config_id, is_enabled=False)

    async def delete_config(self, config_id: str) -> bool:
        nc = await self.get_config(config_id)
        if nc:
            await self.db.delete(nc)
            await self.db.flush()
            return True
        return False

    async def notify(self, event_type: str, title: str, description: str | None = None, severity: str = "info") -> None:
        configs = await self.list_configs(event_type=event_type, is_enabled=True)
        for config in configs:
            await self._send_notification(config, title, description, severity)

    async def _send_notification(self, config: NotificationConfig, title: str, description: str | None, severity: str) -> None:
        event = AdminEvent(
            event_type=config.event_type,
            title=title,
            description=description,
            severity=severity,
            category="security" if "security" in config.event_type else "system",
            source=config.provider_type,
            data={"notification_config_id": str(config.id) if config.id else None},
            is_read=False,
        )
        self.db.add(event)
        await self.db.flush()

    async def alert_generated(self, alert: SecurityAlert) -> None:
        """Fan out a generated alert to enabled admin notification channels.

        Delivery is represented by an AdminEvent so the admin console can show
        and acknowledge it immediately. Provider-specific delivery workers can
        consume the same event later without changing the alert pipeline.
        """
        configs = await self.list_configs(event_type="security_alert", is_enabled=True)
        if configs:
            for config in configs:
                await self._send_notification(config, alert.title, alert.description, str(alert.risk_level))
            return

        # Security alerts must remain visible in the admin notification feed
        # even before an administrator configures an outbound channel.
        self.db.add(
            AdminEvent(
                event_type="security_alert",
                title=alert.title,
                description=alert.description,
                severity=str(alert.risk_level),
                category="security",
                source="security_engine",
                data={"alert_id": str(alert.id) if alert.id else None},
                is_read=False,
            )
        )
        await self.db.flush()
