from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from typing import Any

from sqlalchemy import func, Integer, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import UnitOfWork


class ObservabilityService:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def track_document(self, runtime_id: str, project_id: str) -> None:
        rid = uuid.UUID(runtime_id)
        pid = uuid.UUID(project_id)
        await self.uow.analytics.create(
            metric="documents",
            quantity=1,
            project_id=pid,
            metadata_={"runtime_id": str(rid)},
        )
        await self.uow.commit()

    async def track_chunk(
        self, runtime_id: str, project_id: str, chunk_index: int
    ) -> None:
        rid = uuid.UUID(runtime_id)
        pid = uuid.UUID(project_id)
        await self.uow.analytics.create(
            metric="chunks",
            quantity=1,
            project_id=pid,
            metadata_={"runtime_id": str(rid), "chunk_index": chunk_index},
        )
        await self.uow.commit()

    async def track_embedding(self, runtime_id: str, project_id: str) -> None:
        rid = uuid.UUID(runtime_id)
        pid = uuid.UUID(project_id)
        await self.uow.analytics.create(
            metric="embeddings",
            quantity=1,
            project_id=pid,
            metadata_={"runtime_id": str(rid)},
        )
        await self.uow.commit()

    async def track_index_size(self, runtime_id: str, project_id: str, size: int) -> None:
        rid = uuid.UUID(runtime_id)
        pid = uuid.UUID(project_id)
        await self.uow.analytics.create(
            metric="index_size",
            quantity=size,
            project_id=pid,
            metadata_={"runtime_id": str(rid)},
        )
        await self.uow.commit()

    async def track_provider_usage(
        self,
        runtime_id: str,
        project_id: str,
        provider: str,
        model: str,
        latency_ms: float,
    ) -> None:
        rid = uuid.UUID(runtime_id)
        pid = uuid.UUID(project_id)
        await self.uow.analytics.create(
            metric="provider_usage",
            quantity=1,
            provider=provider,
            model=model,
            project_id=pid,
            metadata_={
                "runtime_id": str(rid),
                "latency_ms": latency_ms,
            },
        )
        await self.uow.commit()

    async def track_token_usage(
        self,
        runtime_id: str,
        project_id: str,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        rid = uuid.UUID(runtime_id)
        pid = uuid.UUID(project_id)
        total = input_tokens + output_tokens
        await self.uow.analytics.create(
            metric="tokens",
            quantity=total,
            project_id=pid,
            metadata_={
                "runtime_id": str(rid),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total,
            },
        )
        await self.uow.commit()

    async def track_latency(
        self,
        runtime_id: str,
        project_id: str,
        operation_type: str,
        latency_ms: float,
    ) -> None:
        rid = uuid.UUID(runtime_id)
        pid = uuid.UUID(project_id)
        await self.uow.analytics.create(
            metric=f"latency_{operation_type}",
            quantity=int(latency_ms),
            project_id=pid,
            metadata_={
                "runtime_id": str(rid),
                "operation_type": operation_type,
                "latency_ms": latency_ms,
            },
        )
        await self.uow.commit()

    async def track_error(
        self,
        runtime_id: str,
        project_id: str,
        category: str,
        count: int = 1,
    ) -> None:
        rid = uuid.UUID(runtime_id)
        pid = uuid.UUID(project_id)
        await self.uow.analytics.create(
            metric="error",
            quantity=count,
            project_id=pid,
            metadata_={
                "runtime_id": str(rid),
                "category": category,
            },
        )
        await self.uow.commit()

    async def track_cache_hit(
        self, runtime_id: str, project_id: str, hit: bool
    ) -> None:
        rid = uuid.UUID(runtime_id)
        pid = uuid.UUID(project_id)
        await self.uow.analytics.create(
            metric="cache_hit" if hit else "cache_miss",
            quantity=1,
            project_id=pid,
            metadata_={"runtime_id": str(rid), "hit": hit},
        )
        await self.uow.commit()

    async def track_retrieval_quality(
        self,
        runtime_id: str,
        project_id: str,
        score: float,
    ) -> None:
        rid = uuid.UUID(runtime_id)
        pid = uuid.UUID(project_id)
        await self.uow.analytics.create(
            metric="retrieval_quality",
            quantity=score,
            project_id=pid,
            metadata_={"runtime_id": str(rid)},
        )
        await self.uow.commit()

    async def get_document_count(self, runtime_id: str, hours: int = 24) -> int:
        rid = uuid.UUID(runtime_id)
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        result = await self.uow.session.execute(
            select(func.sum(self.uow.analytics.model.quantity))
            .where(self.uow.analytics.model.project_id == rid)
            .where(self.uow.analytics.model.metric == "documents")
            .where(self.uow.analytics.model.created_at >= since)
        )
        row = result.scalar()
        return int(row or 0)

    async def get_chunk_count(self, runtime_id: str, hours: int = 24) -> int:
        rid = uuid.UUID(runtime_id)
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        result = await self.uow.session.execute(
            select(func.sum(self.uow.analytics.model.quantity))
            .where(self.uow.analytics.model.project_id == rid)
            .where(self.uow.analytics.model.metric == "chunks")
            .where(self.uow.analytics.model.created_at >= since)
        )
        row = result.scalar()
        return int(row or 0)

    async def get_embedding_count(self, runtime_id: str, hours: int = 24) -> int:
        rid = uuid.UUID(runtime_id)
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        result = await self.uow.session.execute(
            select(func.sum(self.uow.analytics.model.quantity))
            .where(self.uow.analytics.model.project_id == rid)
            .where(self.uow.analytics.model.metric == "embeddings")
            .where(self.uow.analytics.model.created_at >= since)
        )
        row = result.scalar()
        return int(row or 0)

    async def get_index_size(self, runtime_id: str, hours: int = 24) -> int:
        rid = uuid.UUID(runtime_id)
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        result = await self.uow.session.execute(
            select(func.sum(self.uow.analytics.model.quantity))
            .where(self.uow.analytics.model.project_id == rid)
            .where(self.uow.analytics.model.metric == "index_size")
            .where(self.uow.analytics.model.created_at >= since)
        )
        row = result.scalar()
        return int(row or 0)

    async def get_provider_usage(
        self, runtime_id: str, hours: int = 24
    ) -> dict[str, Any]:
        rid = uuid.UUID(runtime_id)
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        result = await self.uow.session.execute(
            select(
                self.uow.analytics.model.provider,
                self.uow.analytics.model.model,
                func.count(self.uow.analytics.model.id).label("request_count"),
                func.avg(
                    self.uow.analytics.model.metadata["latency_ms"].astext.cast(
                        Integer
                    )
                ).label("avg_latency_ms"),
            )
            .where(self.uow.analytics.model.project_id == rid)
            .where(self.uow.analytics.model.metric == "provider_usage")
            .where(self.uow.analytics.model.created_at >= since)
            .group_by(
                self.uow.analytics.model.provider,
                self.uow.analytics.model.model,
            )
        )
        rows = result.all()
        usage: dict[str, Any] = {}
        for provider, model, count, avg_latency in rows:
            key = f"{provider}:{model}" if model else provider
            usage[key] = {
                "request_count": count or 0,
                "avg_latency_ms": round(float(avg_latency or 0), 2),
            }
        return usage

    async def get_token_usage(
        self, runtime_id: str, hours: int = 24
    ) -> dict[str, int]:
        rid = uuid.UUID(runtime_id)
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        result = await self.uow.session.execute(
            select(
                func.sum(
                    self.uow.analytics.model.metadata["input_tokens"]
                    .astext.cast(Integer)
                ).label("input_tokens"),
                func.sum(
                    self.uow.analytics.model.metadata["output_tokens"]
                    .astext.cast(Integer)
                ).label("output_tokens"),
                func.sum(self.uow.analytics.model.quantity).label("total_tokens"),
            )
            .where(self.uow.analytics.model.project_id == rid)
            .where(self.uow.analytics.model.metric == "tokens")
            .where(self.uow.analytics.model.created_at >= since)
        )
        row = result.one_or_none()
        return {
            "input_tokens": int(row.input_tokens or 0) if row else 0,
            "output_tokens": int(row.output_tokens or 0) if row else 0,
            "total_tokens": int(row.total_tokens or 0) if row else 0,
        }

    async def get_latency_by_operation(
        self, runtime_id: str, hours: int = 24
    ) -> dict[str, Any]:
        rid = uuid.UUID(runtime_id)
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        result = await self.uow.session.execute(
            select(
                self.uow.analytics.model.metric,
                func.avg(self.uow.analytics.model.quantity).label("avg_latency_ms"),
                func.max(self.uow.analytics.model.quantity).label("max_latency_ms"),
                func.count(self.uow.analytics.model.id).label("count"),
            )
            .where(self.uow.analytics.model.project_id == rid)
            .where(self.uow.analytics.model.metric.like("latency_%"))
            .where(self.uow.analytics.model.created_at >= since)
            .group_by(self.uow.analytics.model.metric)
        )
        rows = result.all()
        output: dict[str, Any] = {}
        for metric, avg_latency, max_latency, count in rows:
            operation = metric.replace("latency_", "", 1)
            output[operation] = {
                "avg_latency_ms": round(float(avg_latency or 0), 2),
                "max_latency_ms": int(max_latency or 0),
                "count": count or 0,
            }
        return output

    async def get_errors_by_category(
        self, runtime_id: str, hours: int = 24
    ) -> dict[str, int]:
        rid = uuid.UUID(runtime_id)
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        result = await self.uow.session.execute(
            select(
                self.uow.analytics.model.metadata["category"].astext.label("category"),
                func.sum(self.uow.analytics.model.quantity).label("count"),
            )
            .where(self.uow.analytics.model.project_id == rid)
            .where(self.uow.analytics.model.metric == "error")
            .where(self.uow.analytics.model.created_at >= since)
            .group_by(
                self.uow.analytics.model.metadata["category"].astext
            )
        )
        rows = result.all()
        return {category: int(count or 0) for category, count in rows}

    async def get_cache_hit_rate(self, runtime_id: str, hours: int = 24) -> float:
        rid = uuid.UUID(runtime_id)
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        result = await self.uow.session.execute(
            select(
                func.sum(
                    func.case(
                        (self.uow.analytics.model.metric == "cache_hit", self.uow.analytics.model.quantity),
                        else_=0,
                    )
                ).label("hits"),
                func.sum(
                    func.case(
                        (self.uow.analytics.model.metric == "cache_miss", self.uow.analytics.model.quantity),
                        else_=0,
                    )
                ).label("misses"),
            )
            .where(self.uow.analytics.model.project_id == rid)
            .where(
                self.uow.analytics.model.metric.in_(["cache_hit", "cache_miss"])
            )
            .where(self.uow.analytics.model.created_at >= since)
        )
        row = result.one_or_none()
        hits = int(row.hits or 0) if row else 0
        misses = int(row.misses or 0) if row else 0
        total = hits + misses
        if total == 0:
            return 0.0
        return round((hits / total) * 100.0, 2)

    async def get_retrieval_quality(
        self, runtime_id: str, hours: int = 24
    ) -> float:
        rid = uuid.UUID(runtime_id)
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        result = await self.uow.session.execute(
            select(func.avg(self.uow.analytics.model.quantity))
            .where(self.uow.analytics.model.project_id == rid)
            .where(self.uow.analytics.model.metric == "retrieval_quality")
            .where(self.uow.analytics.model.created_at >= since)
        )
        row = result.scalar()
        if row is None:
            return 0.0
        return round(float(row), 2)

    async def get_observability_summary(
        self, runtime_id: str, hours: int = 24
    ) -> dict[str, Any]:
        rid = uuid.UUID(runtime_id)
        return {
            "runtime_id": str(rid),
            "window_hours": hours,
            "documents": await self.get_document_count(str(rid), hours),
            "chunks": await self.get_chunk_count(str(rid), hours),
            "embeddings": await self.get_embedding_count(str(rid), hours),
            "index_size": await self.get_index_size(str(rid), hours),
            "provider_usage": await self.get_provider_usage(str(rid), hours),
            "token_usage": await self.get_token_usage(str(rid), hours),
            "latency_by_operation": await self.get_latency_by_operation(str(rid), hours),
            "errors_by_category": await self.get_errors_by_category(str(rid), hours),
            "cache_hit_rate": await self.get_cache_hit_rate(str(rid), hours),
            "retrieval_quality": await self.get_retrieval_quality(str(rid), hours),
        }