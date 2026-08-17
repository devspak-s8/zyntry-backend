from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from app.repositories import UnitOfWork
from app.schemas.runtimes import RuntimeCreate, RuntimeUpdate


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

    async def get_or_create(
        self, data: RuntimeCreate, default_user_id: uuid.UUID | None = None
    ) -> dict[str, Any]:
        owner_id = data.user_id or default_user_id
        if owner_id is None:
            raise ValueError("user_id is required to create a runtime")

        if data.project_id:
            existing = await self.uow.runtimes.get_by_project(data.project_id)
            if existing:
                return self._to_read(existing)

        runtime = await self.uow.runtimes.create(
            user_id=owner_id,
            project_id=data.project_id,
            organization_id=data.organization_id,
            name=data.name or "Default Runtime",
            environment=data.environment or "development",
            provider=data.provider,
            model=data.model,
            fallback_models=data.fallback_models,
            routing_strategy=data.routing_strategy,
            embedding_model=data.embedding_model,
            vector_store=data.vector_store,
            chunk_size=data.chunk_size,
            chunk_overlap=data.chunk_overlap,
            system_instructions=data.system_instructions,
            security_policies=data.security_policies,
            config=data.config,
            status="active",
            health=100.0,
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

    async def list_by_user(
        self, user_id: uuid.UUID, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        from sqlalchemy import select
        from app.models.runtimes import Runtime

        stmt = (
            select(Runtime)
            .where(Runtime.user_id == user_id)
            .order_by(Runtime.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.uow.session.execute(stmt)
        runtimes = result.scalars().all()
        return [self._to_read(r) for r in runtimes]

    async def list_by_organization(
        self, organization_id: str, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        runtimes = await self.uow.runtimes.get_by_organization(uuid.UUID(organization_id))
        return [self._to_read(r) for r in runtimes[offset : offset + limit]]

    async def update(self, runtime_id: str, data: RuntimeUpdate) -> dict[str, Any]:
        runtime = await self.uow.runtimes.get(uuid.UUID(runtime_id))
        if not runtime:
            raise ValueError("Runtime not found")
        update_data = data.model_dump(exclude_unset=True)
        if "model" in update_data or "embedding_model" in update_data or "provider" in update_data:
            update_data["status"] = "active"
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
        runtime = await self.uow.runtimes.get(uuid.UUID(runtime_id))
        if not runtime:
            raise ValueError("Runtime not found")
        runtime.status = "active"
        runtime.health = 100.0
        runtime.last_build_started = datetime.now(timezone.utc)
        runtime.last_build_completed = datetime.now(timezone.utc)
        runtime.error_message = None
        await self.uow.runtimes.update(
            runtime,
            status="active",
            health=100.0,
            last_build_started=datetime.now(timezone.utc),
            last_build_completed=datetime.now(timezone.utc),
            error_message=None,
        )
        await self.uow.commit()
        return {"runtime_id": str(runtime.id), "status": "active", "trigger": trigger}

    async def cancel(self, runtime_id: str) -> dict[str, Any]:
        runtime = await self.uow.runtimes.get(uuid.UUID(runtime_id))
        if not runtime:
            raise ValueError("Runtime not found")
        await self.uow.runtimes.update(runtime, status="cancelled")
        await self.uow.commit()
        return {"runtime_id": str(runtime.id), "status": "cancelled"}

    async def delete(self, runtime_id: str) -> None:
        runtime = await self.uow.runtimes.get(uuid.UUID(runtime_id))
        if not runtime:
            raise ValueError("Runtime not found")
        await self.uow.runtimes.delete(runtime)
        await self.uow.commit()

    def _to_read(self, runtime: Any) -> dict[str, Any]:
        return {
            "id": str(runtime.id),
            "user_id": str(runtime.user_id),
            "name": getattr(runtime, "name", "Default Runtime"),
            "environment": getattr(runtime, "environment", "development"),
            "project_id": str(runtime.project_id) if runtime.project_id else None,
            "organization_id": str(runtime.organization_id) if runtime.organization_id else None,
            "status": runtime.status,
            "version": runtime.version,
            "provider": runtime.provider,
            "model": runtime.model,
            "fallback_models": getattr(runtime, "fallback_models", []) or [],
            "routing_strategy": getattr(runtime, "routing_strategy", "balanced") or "balanced",
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
            "system_instructions": getattr(runtime, "system_instructions", None),
            "security_policies": getattr(runtime, "security_policies", {}) or {},
            "config": runtime.config,
            "metadata": runtime.metadata_,
            "created_at": runtime.created_at.isoformat() if runtime.created_at else None,
            "updated_at": runtime.updated_at.isoformat() if runtime.updated_at else None,
        }
