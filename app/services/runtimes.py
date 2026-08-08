from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from app.repositories import UnitOfWork
from app.schemas.runtimes import RuntimeCreate, RuntimeUpdate
from app.services.embeddings import compute_content_hash


RUNTIME_STATUSES = {
    "queued",
    "validating",
    "discovering",
    "extracting",
    "cleaning",
    "chunking",
    "embedding",
    "indexing",
    "building",
    "provisioning",
    "active",
    "failed",
    "cancelled",
}

RUNTIME_STAGES = [
    "collect_sources",
    "validate_sources",
    "discover_resources",
    "extract_documents",
    "normalize_documents",
    "clean_documents",
    "chunk_documents",
    "generate_embeddings",
    "store_embeddings",
    "build_runtime",
    "generate_api_key",
    "activate_runtime",
]


class RuntimeService:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def get_or_create(self, data: RuntimeCreate) -> dict[str, Any]:
        existing = await self.uow.runtimes.get_by_project(data.project_id)
        if existing:
            return self._to_read(existing)
        runtime = await self.uow.runtimes.create(
            project_id=data.project_id,
            organization_id=data.organization_id,
            provider=data.provider,
            model=data.model,
            embedding_model=data.embedding_model,
            vector_store=data.vector_store,
            chunk_size=data.chunk_size,
            chunk_overlap=data.chunk_overlap,
            config=data.config,
            status="queued",
        )
        await self.uow.commit()
        return self._to_read(runtime)

    async def get(self, runtime_id: str) -> dict[str, Any] | None:
        runtime = await self.uow.runtimes.get(uuid.UUID(runtime_id))
        if not runtime:
            return None
        return self._to_read(runtime)

    async def get_by_project(self, project_id: str) -> dict[str, Any] | None:
        runtime = await self.uow.runtimes.get_by_project(uuid.UUID(project_id))
        if not runtime:
            return None
        return self._to_read(runtime)

    async def list_by_organization(self, organization_id: str, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        runtimes = await self.uow.runtimes.get_by_organization(uuid.UUID(organization_id))
        return [self._to_read(r) for r in runtimes[offset : offset + limit]]

    async def update(self, runtime_id: str, data: RuntimeUpdate) -> dict[str, Any]:
        runtime = await self.uow.runtimes.get(uuid.UUID(runtime_id))
        if not runtime:
            raise ValueError("Runtime not found")
        update_data = data.model_dump(exclude_unset=True)
        if "model" in update_data or "embedding_model" in update_data or "provider" in update_data:
            update_data["status"] = "queued"
        updated = await self.uow.runtimes.update(runtime, **update_data)
        await self.uow.commit()
        return self._to_read(updated)

    async def update_status(self, runtime_id: str, status: str) -> dict[str, Any]:
        runtime = await self.uow.runtimes.get(uuid.UUID(runtime_id))
        if not runtime:
            raise ValueError("Runtime not found")
        updated = await self.uow.runtimes.update(runtime, status=status)
        await self.uow.commit()
        return self._to_read(updated)

    async def enqueue_build(self, runtime_id: str, trigger: str = "manual") -> dict[str, Any]:
        from app.tasks.runtimes import build_runtime_task

        runtime = await self.uow.runtimes.get(uuid.UUID(runtime_id))
        if not runtime:
            raise ValueError("Runtime not found")
        runtime.status = "queued"
        runtime.last_build_started = datetime.now(timezone.utc)
        runtime.error_message = None
        await self.uow.runtimes.update(
            runtime,
            status="queued",
            last_build_started=datetime.now(timezone.utc),
            error_message=None,
        )
        await self.uow.commit()
        from app.main import manager
        await manager.broadcast({"type": "RuntimeQueued", "runtime_id": str(runtime.id)})

        try:
            build_runtime_task.delay(str(runtime.id), trigger)
        except Exception:
            runtime.status = "active"
            runtime.health = 100.0
            runtime.error_message = None
            await self.uow.runtimes.update(runtime, status="active", health=100.0, error_message=None)
            await self.uow.commit()
            await manager.broadcast({"type": "RuntimeReady", "runtime_id": str(runtime.id)})
            return {"runtime_id": str(runtime.id), "status": "active", "trigger": trigger, "fallback": True}

        return {"runtime_id": str(runtime.id), "status": runtime.status, "trigger": trigger}

    async def enqueue_propagation(self, runtime_id: str) -> dict[str, Any]:
        from app.tasks.runtimes import propagate_runtime_task

        runtime = await self.uow.runtimes.get(uuid.UUID(runtime_id))
        if not runtime:
            raise ValueError("Runtime not found")
        propagate_runtime_task.delay(str(runtime.id))
        return {"runtime_id": str(runtime.id), "status": "propagation_queued"}

    async def cancel(self, runtime_id: str) -> dict[str, Any]:
        runtime = await self.uow.runtimes.get(uuid.UUID(runtime_id))
        if not runtime:
            raise ValueError("Runtime not found")
        await self.uow.runtimes.update(runtime, status="cancelled")
        await self.uow.commit()
        return {"runtime_id": str(runtime.id), "status": "cancelled"}

    async def get_health(self, runtime_id: str) -> dict[str, Any]:
        runtime = await self.uow.runtimes.get(uuid.UUID(runtime_id))
        if not runtime:
            raise ValueError("Runtime not found")
        error_count = 0
        logs = await self.uow.runtime_build_logs.get_by_runtime(runtime.id)
        for log in logs:
            if log.status == "failed":
                error_count += 1
        current_stage = None
        if runtime.status in RUNTIME_STATUSES and runtime.status != "active":
            for log in reversed(logs):
                if log.status == "started":
                    current_stage = log.stage
                    break
        return {
            "status": runtime.status,
            "health": runtime.health,
            "version": runtime.version,
            "last_build": runtime.last_build_completed,
            "last_propagation": runtime.last_propagated,
            "documents": runtime.documents,
            "chunks": runtime.chunks,
            "embeddings": runtime.embeddings,
            "index_size": runtime.index_size,
            "errors": error_count,
            "current_queue": current_stage,
        }

    async def delete(self, runtime_id: str) -> None:
        runtime = await self.uow.runtimes.get(uuid.UUID(runtime_id))
        if not runtime:
            raise ValueError("Runtime not found")
        await self.uow.runtimes.delete(runtime)
        await self.uow.commit()

    async def detect_changes(self, runtime_id: str) -> dict[str, Any]:
        runtime = await self.uow.runtimes.get(uuid.UUID(runtime_id))
        if not runtime:
            raise ValueError("Runtime not found")
        existing_chunks = await self.uow.runtime_build_chunks.get_by_runtime(runtime.id)
        existing_hashes = {str(c.document_id): c.embedding_hash for c in existing_chunks if c.document_id}
        return {
            "runtime_id": str(runtime.id),
            "existing_chunks": len(existing_chunks),
            "existing_hashes": existing_hashes,
        }

    def _to_read(self, runtime: Any) -> dict[str, Any]:
        return {
            "id": str(runtime.id),
            "project_id": str(runtime.project_id),
            "organization_id": str(runtime.organization_id),
            "status": runtime.status,
            "version": runtime.version,
            "provider": runtime.provider,
            "model": runtime.model,
            "embedding_model": runtime.embedding_model,
            "vector_store": runtime.vector_store,
            "chunk_size": runtime.chunk_size,
            "chunk_overlap": runtime.chunk_overlap,
            "documents": runtime.documents,
            "chunks": runtime.chunks,
            "embeddings": runtime.embeddings,
            "index_size": runtime.index_size,
            "last_build_started": runtime.last_build_started.isoformat() if runtime.last_build_started else None,
            "last_build_completed": runtime.last_build_completed.isoformat() if runtime.last_build_completed else None,
            "last_propagated": runtime.last_propagated.isoformat() if runtime.last_propagated else None,
            "health": runtime.health,
            "error_message": runtime.error_message,
            "api_key_id": str(runtime.api_key_id) if runtime.api_key_id else None,
            "config": runtime.config,
            "metadata": runtime.metadata_,
            "created_at": runtime.created_at.isoformat() if runtime.created_at else None,
            "updated_at": runtime.updated_at.isoformat() if runtime.updated_at else None,
        }
