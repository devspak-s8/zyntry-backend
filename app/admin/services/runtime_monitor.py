from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.repositories import IPRecordRepository
from app.core.cache import cache as redis_cache
from app.models.runtimes import Runtime


class RuntimeMonitorService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._ip_repo = IPRecordRepository(db)

    async def get_all_runtimes(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        result = await self.db.execute(select(Runtime).limit(limit).offset(offset))
        rows = result.scalars().all()
        results = []
        for row in rows:
            runtime_id = str(row.id) if row.id else ""
            avg_latency = await self._get_avg_latency(runtime_id)
            avg_cost = await self._get_avg_cost(runtime_id)
            invocation_count = await self._get_invocation_count(runtime_id)
            error_count = await self._get_error_count(runtime_id)
            cache_hit_rate = await self._get_cache_hit_rate(runtime_id)
            queue_time = await self._get_queue_time(runtime_id)
            connected_sources = await self._count_connected_sources(runtime_id)
            connected_tools = await self._count_connected_tools(runtime_id) if connected_sources > 0 else 0
            results.append({
                "id": runtime_id,
                "project_id": str(row.project_id) if row.project_id else None,
                "organization_id": str(row.organization_id) if row.organization_id else None,
                "name": row.name,
                "status": row.status,
                "provider": row.provider,
                "model": row.model,
                "embedding_model": row.embedding_model,
                "vector_store": row.vector_store,
                "config": row.config,
                "documents": row.documents,
                "chunks": row.chunks,
                "embeddings": row.embeddings,
                "index_size": row.index_size,
                "health": row.health,
                "error_message": row.error_message,
                "api_key_id": str(row.api_key_id) if row.api_key_id else None,
                "avg_latency_ms": avg_latency,
                "avg_cost": float(avg_cost) if avg_cost else None,
                "invocation_count": invocation_count,
                "error_count": error_count,
                "cache_hit_rate": cache_hit_rate,
                "queue_time_ms": queue_time,
                "connected_sources": connected_sources,
                "connected_tools": connected_tools,
            })
        return results

    async def _get_avg_latency(self, runtime_id: str) -> float | None:
        return None

    async def _get_avg_cost(self, runtime_id: str) -> Decimal | None:
        return None

    async def _get_invocation_count(self, runtime_id: str) -> int:
        return 0

    async def _get_error_count(self, runtime_id: str) -> int:
        return 0

    async def _get_cache_hit_rate(self, runtime_id: str) -> float:
        return 0.0

    async def _get_queue_time(self, runtime_id: str) -> float:
        return 0.0

    async def _count_connected_sources(self, runtime_id: str) -> int:
        return 0

    async def _count_connected_tools(self, project_id: str) -> int:
        return 0

    async def _get_last_invocation(self, runtime_id: str) -> datetime | None:
        return None

    async def get_runtime_detail(self, runtime_id: str) -> dict[str, Any] | None:
        result = await self.db.execute(select(Runtime).where(Runtime.id == runtime_id))
        runtime = result.scalar_one_or_none()
        if runtime is None:
            return None
        return {
            "id": str(runtime.id) if runtime.id else None,
            "project_id": str(runtime.project_id) if runtime.project_id else None,
            "organization_id": str(runtime.organization_id) if runtime.organization_id else None,
            "name": runtime.name,
            "status": runtime.status,
            "provider": runtime.provider,
            "model": runtime.model,
            "embedding_model": runtime.embedding_model,
            "vector_store": runtime.vector_store,
            "config": runtime.config,
            "documents": runtime.documents,
            "chunks": runtime.chunks,
            "embeddings": runtime.embeddings,
            "index_size": runtime.index_size,
            "health": runtime.health,
            "error_message": runtime.error_message,
            "created_at": runtime.created_at.isoformat() if runtime.created_at else "",
            "updated_at": runtime.updated_at.isoformat() if runtime.updated_at else "",
            "disabled": runtime.disabled,
            "disabled_by_admin": runtime.disabled_by_admin,
        }

    async def disable_runtime(self, runtime_id: str) -> bool:
        result = await self.db.execute(select(Runtime).where(Runtime.id == runtime_id))
        runtime = result.scalar_one_or_none()
        if runtime:
            runtime.disabled = True
            runtime.disabled_by_admin = True
            await self.db.flush()
        return True

    async def restart_runtime(self, runtime_id: str) -> bool:
        result = await self.db.execute(select(Runtime).where(Runtime.id == runtime_id))
        runtime = result.scalar_one_or_none()
        if runtime:
            runtime.status = "queued"
            await self.db.flush()
        return True

    async def flush_cache(self, runtime_id: str) -> bool:
        await redis_cache.delete(f"runtime:{runtime_id}:cache")
        await redis_cache.delete(f"runtime:{runtime_id}:config")
        return True

    async def regenerate_runtime(self, runtime_id: str) -> bool:
        await redis_cache.delete(f"runtime:{runtime_id}:cache")
        await redis_cache.delete(f"runtime:{runtime_id}:config")
        return True

    async def delete_runtime(self, runtime_id: str) -> bool:
        result = await self.db.execute(select(Runtime).where(Runtime.id == runtime_id))
        runtime = result.scalar_one_or_none()
        if runtime:
            await self.db.delete(runtime)
            await self.db.flush()
        return True
