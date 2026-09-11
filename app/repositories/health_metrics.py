from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.health_metrics import HealthMetric, RuntimeHealthCheck
from app.repositories.base import BaseRepository


class HealthMetricRepository(BaseRepository[HealthMetric]):
    model = HealthMetric


class RuntimeHealthCheckRepository(BaseRepository[RuntimeHealthCheck]):
    model = RuntimeHealthCheck

    async def get_latest_by_runtime(self, runtime_id: uuid.UUID) -> RuntimeHealthCheck | None:
        result = await self.session.execute(
            select(RuntimeHealthCheck)
            .where(RuntimeHealthCheck.runtime_id == runtime_id)
            .order_by(RuntimeHealthCheck.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
