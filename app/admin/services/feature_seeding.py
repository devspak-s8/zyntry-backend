from __future__ import annotations

import logging

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.feature_registry import SYSTEM_FEATURES
from app.admin.models import FeatureFlag

logger = logging.getLogger(__name__)


async def seed_system_feature_flags(db: AsyncSession) -> list[str]:
    """Create missing system flags without modifying any existing flag."""
    values = [
        {
            "key": feature.key,
            "name": feature.name,
            "description": feature.description,
            "scope": feature.scope.value,
            "flag_type": feature.flag_type.value,
            "enabled": feature.enabled,
            "default_value": feature.default_value,
            "rollout_percentage": feature.rollout_percentage,
            "allowlist": [],
            "is_system": True,
        }
        for feature in SYSTEM_FEATURES
    ]
    statement = (
        insert(FeatureFlag)
        .values(values)
        .on_conflict_do_nothing(index_elements=[FeatureFlag.key])
        .returning(FeatureFlag.key)
    )
    result = await db.execute(statement)
    created = list(result.scalars().all())
    await db.commit()
    logger.info(
        "System feature seed complete: %d created, %d already present",
        len(created),
        len(values) - len(created),
    )
    return created
