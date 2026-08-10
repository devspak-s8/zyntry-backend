from __future__ import annotations

import hashlib
import json
import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.constants import FeatureFlagType
from app.admin.models import FeatureFlag
from app.admin.repositories import FeatureFlagRepository
from app.core.redis import redis_client
from app.models.users import User

logger = logging.getLogger(__name__)

FEATURE_FLAG_CACHE_TTL_SECONDS = 30


def _flag_type_value(flag: FeatureFlag) -> str:
    return (
        flag.flag_type.value if isinstance(flag.flag_type, FeatureFlagType) else str(flag.flag_type)
    )


def _stable_rollout_bucket(key: str, subject: str) -> int:
    digest = hashlib.sha256(f"{key}:{subject}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % 100


def evaluate_feature_flag(
    flag: FeatureFlag | None,
    *,
    user_id: uuid.UUID | str,
    organization_id: uuid.UUID | str | None,
    email: str,
) -> bool:
    """Evaluate a flag consistently for the same user or organization."""
    if flag is None or not flag.enabled:
        return False

    targets = {
        f"user:{str(user_id).lower()}",
        f"email:{email.strip().lower()}",
    }
    if organization_id is not None:
        targets.add(f"org:{str(organization_id).lower()}")

    allowlist = {entry.strip().lower() for entry in (flag.allowlist or [])}
    if targets & allowlist:
        return True

    flag_type = _flag_type_value(flag)
    if flag_type == FeatureFlagType.TOGGLE.value:
        return bool(flag.default_value)

    percentage = max(0, min(100, flag.rollout_percentage))
    if percentage == 0:
        return bool(flag.default_value)
    if percentage == 100:
        return True

    # Prefer organization identity so an entire tenant gets a consistent experience.
    subject = str(organization_id or user_id).lower()
    return _stable_rollout_bucket(flag.key, subject) < percentage


class FeatureFlagService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._repo = FeatureFlagRepository(db)

    async def get_by_key(self, key: str) -> FeatureFlag | None:
        cache_key = f"feature-flag:{key}"
        try:
            cached = await redis_client.get(cache_key)
            if cached:
                data = json.loads(cached)
                return FeatureFlag(**data)
        except Exception:
            logger.warning("Feature flag cache read failed", exc_info=True)

        flag = await self._repo.get_by_key(key)
        if flag is not None:
            try:
                await redis_client.set(
                    cache_key,
                    json.dumps(
                        {
                            "id": str(flag.id),
                            "key": flag.key,
                            "name": flag.name,
                            "description": flag.description,
                            "scope": flag.scope,
                            "flag_type": _flag_type_value(flag),
                            "enabled": flag.enabled,
                            "default_value": flag.default_value,
                            "rollout_percentage": flag.rollout_percentage,
                            "allowlist": flag.allowlist,
                            "is_system": flag.is_system,
                            "updated_by": str(flag.updated_by) if flag.updated_by else None,
                        }
                    ),
                    ex=FEATURE_FLAG_CACHE_TTL_SECONDS,
                )
            except Exception:
                logger.warning("Feature flag cache write failed", exc_info=True)
        return flag

    async def invalidate(self, key: str) -> None:
        try:
            await redis_client.delete(f"feature-flag:{key}")
        except Exception:
            logger.warning("Feature flag cache invalidation failed", exc_info=True)

    async def is_enabled(self, key: str, user: User) -> bool:
        flag = await self.get_by_key(key)
        return evaluate_feature_flag(
            flag,
            user_id=user.id,
            organization_id=user.organization_id,
            email=user.email,
        )

    async def evaluate_all(self, user: User) -> dict[str, bool]:
        flags = await self._repo.list_all(limit=100, offset=0)
        return {
            flag.key: evaluate_feature_flag(
                flag,
                user_id=user.id,
                organization_id=user.organization_id,
                email=user.email,
            )
            for flag in flags
        }

    async def list_all(
        self, scope: str | None = None, enabled_only: bool = False, limit: int = 50, offset: int = 0
    ) -> list[FeatureFlag]:
        return await self._repo.list_all(
            scope=scope, enabled_only=enabled_only, limit=limit, offset=offset
        )

    async def create_flag(
        self,
        key: str,
        name: str,
        description: str | None,
        scope: str,
        flag_type: str,
        enabled: bool,
        default_value: bool | None,
        rollout_percentage: int,
        allowlist: list[str] | None,
        updated_by: uuid.UUID | None = None,
    ) -> FeatureFlag:
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
            updated_by=updated_by,
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
        await self.invalidate(key)
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
