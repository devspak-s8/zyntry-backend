from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.models.health_metrics import HealthMetric, RuntimeHealthCheck
from app.models.runtimes import Runtime
from app.repositories import UnitOfWork
from app.repositories.base import BaseRepository


class HealthMetricRepository(BaseRepository[HealthMetric]):
    model: type[HealthMetric] = HealthMetric

    async def get_by_runtime_and_type(
        self, runtime_id: uuid.UUID, metric_type: str, hours: int = 24
    ) -> list[HealthMetric]:
        since = datetime.now(UTC) - timedelta(hours=hours)
        result = await self.session.execute(
            select(HealthMetric)
            .where(HealthMetric.runtime_id == runtime_id)
            .where(HealthMetric.metric_type == metric_type)
            .where(HealthMetric.created_at >= since)
            .order_by(HealthMetric.created_at.asc())
        )
        return list(result.scalars().all())


class RuntimeHealthCheckRepository(BaseRepository[RuntimeHealthCheck]):
    model: type[RuntimeHealthCheck] = RuntimeHealthCheck

    async def get_latest_by_runtime(self, runtime_id: uuid.UUID) -> RuntimeHealthCheck | None:
        result = await self.session.execute(
            select(RuntimeHealthCheck)
            .where(RuntimeHealthCheck.runtime_id == runtime_id)
            .order_by(RuntimeHealthCheck.created_at.desc())
            .limit(1)
        )
        return result.scalars().first()


class HealthService:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def get_runtime_health(self, runtime_id: str) -> dict[str, Any]:
        rid = uuid.UUID(runtime_id)
        runtime = await self.uow.runtimes.get(rid)
        if not runtime:
            raise ValueError("Runtime not found")

        metrics = await self._get_recent_metrics(rid, hours=24)
        checks = await self._get_recent_health_checks(rid, hours=24)

        embedding_latency_ms = self._avg_metric(metrics, "embedding_latency_ms")
        retrieval_latency_ms = self._avg_metric(metrics, "retrieval_latency_ms")
        llm_latency_ms = self._avg_metric(metrics, "llm_latency_ms")
        total_tokens = sum(m.value for m in metrics if m.metric_type == "tokens")
        cache_hits = sum(m.value for m in metrics if m.metric_type == "cache_hit")
        cache_misses = sum(m.value for m in metrics if m.metric_type == "cache_miss")
        cache_hit_rate = (
            (cache_hits / (cache_hits + cache_misses) * 100.0)
            if (cache_hits + cache_misses) > 0
            else 0.0
        )
        error_count = sum(m.value for m in metrics if m.metric_type == "error")
        index_size = runtime.index_size
        storage_usage = index_size + self._get_cache_size_estimate(rid)
        memory_usage_mb = self._estimate_memory_usage(runtime)
        worker_queue_depth = self._get_queue_depth(runtime)
        last_sync_success = self._get_last_sync_timestamp(runtime, checks)
        last_propagation_success = self._get_last_propagation_timestamp(runtime, checks)
        retrieval_quality = self._compute_retrieval_quality(rid)

        health_score = self._compute_health_score(
            last_sync_success=last_sync_success,
            embedding_latency_ms=embedding_latency_ms,
            cache_hit_rate=cache_hit_rate,
            index_size=index_size,
            error_count=error_count,
            total_operations=max(1, cache_hits + cache_misses + error_count),
        )

        return {
            "runtime_id": str(runtime.id),
            "status": runtime.status,
            "health": runtime.health,
            "version": runtime.version,
            "last_build": runtime.last_build_completed,
            "last_propagation": runtime.last_propagated,
            "documents": runtime.documents,
            "chunks": runtime.chunks,
            "embeddings": runtime.embeddings,
            "embedding_latency_ms": round(embedding_latency_ms, 2),
            "retrieval_latency_ms": round(retrieval_latency_ms, 2),
            "llm_latency_ms": round(llm_latency_ms, 2),
            "token_usage": total_tokens,
            "storage_usage": storage_usage,
            "index_size": index_size,
            "memory_usage_mb": round(memory_usage_mb, 2),
            "worker_queue_depth": worker_queue_depth,
            "last_sync_success": last_sync_success,
            "last_propagation_success": last_propagation_success,
            "health_score": round(health_score, 2),
            "error_count": error_count,
            "errors": int(error_count),
            "current_queue": runtime.status if runtime.status in ("queued", "building", "provisioning") else None,
            "cache_hit_rate": round(cache_hit_rate, 2),
            "retrieval_quality": round(retrieval_quality, 2),
        }

    async def record_metric(self, runtime_id: str, metric_type: str, value: float) -> None:
        rid = uuid.UUID(runtime_id)
        runtime = await self.uow.runtimes.get(rid)
        if not runtime:
            raise ValueError("Runtime not found")
        metric = await self.uow.health_metrics.create(
            runtime_id=rid,
            metric_type=metric_type,
            value=value,
        )
        await self.uow.commit()
        return metric

    async def get_metrics_summary(self, runtime_id: str, hours: int = 24) -> dict[str, Any]:
        rid = uuid.UUID(runtime_id)
        runtime = await self.uow.runtimes.get(rid)
        if not runtime:
            raise ValueError("Runtime not found")

        metrics = await self._get_recent_metrics(rid, hours=hours)
        checks = await self._get_recent_health_checks(rid, hours=hours)

        by_type: dict[str, list[float]] = {}
        for m in metrics:
            by_type.setdefault(m.metric_type, []).append(m.value)

        summary: dict[str, Any] = {
            "runtime_id": str(rid),
            "window_hours": hours,
            "period_start": (datetime.now(UTC) - timedelta(hours=hours)).isoformat(),
            "period_end": datetime.now(UTC).isoformat(),
            "metrics_by_type": {},
        }

        for mtype, values in by_type.items():
            summary["metrics_by_type"][mtype] = {
                "count": len(values),
                "avg": round(sum(values) / len(values), 4),
                "min": round(min(values), 4),
                "max": round(max(values), 4),
                "total": round(sum(values), 4),
            }

        if checks:
            latest = checks[-1]
            summary["latest_health_check"] = {
                "health_score": latest.health_score,
                "status": latest.status,
                "embedding_latency_ms": latest.embedding_latency_ms,
                "retrieval_latency_ms": latest.retrieval_latency_ms,
                "llm_latency_ms": latest.llm_latency_ms,
                "token_usage": latest.token_usage,
                "error_count": latest.error_count,
                "cache_hit_rate": latest.cache_hit_rate,
                "retrieval_quality": latest.retrieval_quality,
            }

        return summary

    async def record_health_check(
        self,
        runtime_id: str,
        status: str,
        health_score: float,
        embedding_latency_ms: float | None = None,
        retrieval_latency_ms: float | None = None,
        llm_latency_ms: float | None = None,
        token_usage: int = 0,
        storage_usage: int = 0,
        index_size: int = 0,
        memory_usage_mb: float | None = None,
        worker_queue_depth: int = 0,
        last_sync_success: str | None = None,
        last_propagation_success: str | None = None,
        error_count: int = 0,
        cache_hit_rate: float | None = None,
        retrieval_quality: float | None = None,
        details: dict | None = None,
    ) -> RuntimeHealthCheck:
        rid = uuid.UUID(runtime_id)
        runtime = await self.uow.runtimes.get(rid)
        if not runtime:
            raise ValueError("Runtime not found")

        check = await self.uow.runtime_health_checks.create(
            runtime_id=rid,
            status=status,
            health_score=health_score,
            embedding_latency_ms=embedding_latency_ms,
            retrieval_latency_ms=retrieval_latency_ms,
            llm_latency_ms=llm_latency_ms,
            token_usage=token_usage,
            storage_usage=storage_usage,
            index_size=index_size,
            memory_usage_mb=memory_usage_mb,
            worker_queue_depth=worker_queue_depth,
            last_sync_success=last_sync_success,
            last_propagation_success=last_propagation_success,
            error_count=error_count,
            cache_hit_rate=cache_hit_rate,
            retrieval_quality=retrieval_quality,
            details=details or {},
        )
        await self.uow.commit()
        return check

    async def _get_recent_metrics(
        self, runtime_id: uuid.UUID, hours: int = 24
    ) -> list[HealthMetric]:
        since = datetime.now(UTC) - timedelta(hours=hours)
        result = await self.uow.session.execute(
            select(HealthMetric)
            .where(HealthMetric.runtime_id == runtime_id)
            .where(HealthMetric.created_at >= since)
            .order_by(HealthMetric.created_at.asc())
        )
        return list(result.scalars().all())

    async def _get_recent_health_checks(
        self, runtime_id: uuid.UUID, hours: int = 24
    ) -> list[RuntimeHealthCheck]:
        since = datetime.now(UTC) - timedelta(hours=hours)
        result = await self.uow.session.execute(
            select(RuntimeHealthCheck)
            .where(RuntimeHealthCheck.runtime_id == runtime_id)
            .where(RuntimeHealthCheck.created_at >= since)
            .order_by(RuntimeHealthCheck.created_at.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    def _avg_metric(metrics: list[HealthMetric], metric_type: str) -> float:
        values = [m.value for m in metrics if m.metric_type == metric_type]
        if not values:
            return 0.0
        return sum(values) / len(values)

    @staticmethod
    def _get_cache_size_estimate(runtime_id: uuid.UUID) -> int:
        return 0

    @staticmethod
    def _estimate_memory_usage(runtime: Runtime) -> float:
        base = 50.0
        embedding_overhead = runtime.embeddings * 0.001
        index_overhead = runtime.index_size * 0.0001
        return round(base + embedding_overhead + index_overhead, 2)

    @staticmethod
    def _get_queue_depth(runtime: Runtime) -> int:
        if runtime.status in ("queued", "building", "provisioning"):
            return 1
        return 0

    @staticmethod
    def _get_last_sync_timestamp(runtime: Runtime, checks: list[RuntimeHealthCheck]) -> str | None:
        if runtime.last_build_completed:
            return runtime.last_build_completed.isoformat()
        if checks:
            latest = max(checks, key=lambda c: c.created_at)
            if latest.status == "healthy":
                return latest.created_at.isoformat()
        return None

    @staticmethod
    def _get_last_propagation_timestamp(runtime: Runtime, checks: list[RuntimeHealthCheck]) -> str | None:
        if runtime.last_propagated:
            return runtime.last_propagated.isoformat()
        if checks:
            for check in reversed(checks):
                if check.details.get("propagation_success"):
                    return check.created_at.isoformat()
        return None

    @staticmethod
    def _compute_retrieval_quality(runtime_id: uuid.UUID) -> float:
        return 0.75

    @staticmethod
    def _compute_health_score(
        last_sync_success: str | None,
        embedding_latency_ms: float,
        cache_hit_rate: float,
        index_size: int,
        error_count: int,
        total_operations: int,
    ) -> float:
        sync_score = 0.0
        if last_sync_success is not None:
            try:
                last_sync = datetime.fromisoformat(last_sync_success)
                age_hours = (datetime.now(UTC) - last_sync).total_seconds() / 3600.0
                if age_hours <= 1:
                    sync_score = 100.0
                elif age_hours <= 24:
                    sync_score = 100.0 - (age_hours - 1) * (100.0 / 23.0)
                else:
                    sync_score = 0.0
            except (ValueError, TypeError):
                sync_score = 0.0

        latency_score = 0.0
        if embedding_latency_ms <= 0:
            latency_score = 100.0
        elif embedding_latency_ms < 500:
            latency_score = 100.0
        elif embedding_latency_ms < 1000:
            latency_score = 100.0 - ((embedding_latency_ms - 500) / 500.0) * 50.0
        else:
            latency_score = max(0.0, 50.0 - ((embedding_latency_ms - 1000) / 1000.0) * 50.0)

        cache_score = 100.0 if cache_hit_rate > 80.0 else max(0.0, (cache_hit_rate / 80.0) * 100.0)

        index_score = 100.0 if index_size <= 50000 else max(0.0, 100.0 - ((index_size - 50000) / 50000.0) * 100.0)

        error_rate = (error_count / max(1, total_operations)) * 100.0
        error_score = 100.0 if error_rate < 1.0 else max(0.0, 100.0 - (error_rate - 1.0) * 10.0)

        score = (
            sync_score * 0.30
            + latency_score * 0.20
            + cache_score * 0.20
            + index_score * 0.15
            + error_score * 0.15
        )
        return max(0.0, min(100.0, round(score, 2)))
