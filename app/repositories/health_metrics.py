from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.health_metrics import HealthMetric, RuntimeHealthCheck
from app.repositories.base import BaseRepository


class HealthMetricRepository(BaseRepository[HealthMetric]):
    model = HealthMetric


class RuntimeHealthCheckRepository(BaseRepository[RuntimeHealthCheck]):
    model = RuntimeHealthCheck