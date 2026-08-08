from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.models import FeatureFlag
from app.admin.repositories import FeatureFlagRepository


class FeatureFlagService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._repo = FeatureFlagRepository(db)

    async def get_by_key(self, key: str) -> FeatureFlag | None:
        return await self._repo.get_by_key(key)

    async def list_all(self, scope: str | None = None, enabled_only: bool = False, limit: int = 50, offset: int = 0) -> list[FeatureFlag]:
        return await self._repo.list_all(scope=scope, enabled_only=enabled_only, limit=limit, offset=offset)

    async def create_flag(self, key: str, name: str, description: str | None, scope: str, flag_type: str, enabled: bool, default_value: bool | None, rollout_percentage: int, allowlist: list[str] | None) -> FeatureFlag:
        flag = FeatureFlag(
            key=key,
            name=name,
            description=description,
            scope=scope,
            flag_type=flag_type,
            enabled=enabled,
            default_value=default_value,
            rollout_percentage=rollout_percentage,
            allowlist=allowlist,
        )
        self.db.add(flag)
        await self.db.flush()
        return flag

    async def update_flag(self, key: str, **kwargs: Any) -> FeatureFlag | None:
        flag = await self._repo.get_by_key(key)
        if flag is None:
            return None
        for k, v in kwargs.items():
            if hasattr(flag, k):
                setattr(flag, k, v)
        await self.db.flush()
        return flag

    async def enable_flag(self, key: str) -> FeatureFlag | None:
        return await self.update_flag(key, enabled=True)

    async def disable_flag(self, key: str) -> FeatureFlag | None:
        return await self.update_flag(key, enabled=False)

    async def delete_flag(self, key: str) -> bool:
        flag = await self._repo.get_by_key(key)
        if flag:
            await self.db.delete(flag)
            await self.db.flush()
            return True
        return False