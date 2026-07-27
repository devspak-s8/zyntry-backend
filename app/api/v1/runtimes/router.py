from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.core.database import get_session
from app.models.users import User
from app.repositories import UnitOfWork
from app.schemas.runtimes import (
    RuntimeBuildChunkRead,
    RuntimeBuildLogRead,
    RuntimeCreate,
    RuntimeHealthResponse,
    RuntimeRead,
    RuntimeUpdate,
)
from app.services.health import HealthService
from app.services.runtimes import RuntimeService

router = APIRouter(prefix="/runtimes", tags=["runtimes"])


@router.get("", response_model=list[RuntimeRead])
async def list_runtimes(
    current_user: Annotated[User, Depends(get_current_user)],
    organization_id: Annotated[str | None, Query()] = None,
    project_id: Annotated[str | None, Query()] = None,
    db: AsyncSession = Depends(get_session),
) -> list[RuntimeRead]:
    uow = UnitOfWork(db)
    service = RuntimeService(uow)
    if project_id:
        runtime = await service.get_by_project(project_id)
        return [runtime] if runtime else []
    if organization_id:
        return await service.list_by_organization(organization_id)
    runtimes = await uow.runtimes.list_active()
    return [service._to_read(r) for r in runtimes]


@router.post("", response_model=RuntimeRead, status_code=status.HTTP_201_CREATED)
async def create_runtime(
    body: RuntimeCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> RuntimeRead:
    uow = UnitOfWork(db)
    service = RuntimeService(uow)
    runtime = await service.get_or_create(body)
    return RuntimeRead(**runtime)


@router.get("/{runtime_id}", response_model=RuntimeRead)
async def get_runtime(
    runtime_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> RuntimeRead:
    uow = UnitOfWork(db)
    service = RuntimeService(uow)
    runtime = await service.get(runtime_id)
    if not runtime:
        raise HTTPException(status_code=404, detail="Runtime not found")
    return RuntimeRead(**runtime)


@router.get("/project/{project_id}", response_model=RuntimeRead)
async def get_runtime_by_project(
    project_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> RuntimeRead:
    try:
        uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project_id format")
    uow = UnitOfWork(db)
    service = RuntimeService(uow)
    runtime = await service.get_by_project(project_id)
    if not runtime:
        raise HTTPException(status_code=404, detail="Runtime not found")
    return RuntimeRead(**runtime)


@router.patch("/{runtime_id}", response_model=RuntimeRead)
async def update_runtime(
    runtime_id: str,
    body: RuntimeUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> RuntimeRead:
    uow = UnitOfWork(db)
    service = RuntimeService(uow)
    runtime = await service.update(runtime_id, body)
    return RuntimeRead(**runtime)


@router.post("/{runtime_id}/rebuild", response_model=dict)
async def rebuild_runtime(
    runtime_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> dict:
    uow = UnitOfWork(db)
    service = RuntimeService(uow)
    result = await service.enqueue_build(runtime_id, trigger="manual")
    return result


@router.post("/{runtime_id}/propagate", response_model=dict)
async def propagate_runtime(
    runtime_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> dict:
    uow = UnitOfWork(db)
    service = RuntimeService(uow)
    result = await service.enqueue_propagation(runtime_id)
    return result


@router.post("/{runtime_id}/cancel", response_model=dict)
async def cancel_runtime(
    runtime_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> dict:
    uow = UnitOfWork(db)
    service = RuntimeService(uow)
    result = await service.cancel(runtime_id)
    return result


@router.get("/{runtime_id}/health", response_model=RuntimeHealthResponse)
async def get_runtime_health(
    runtime_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> RuntimeHealthResponse:
    uow = UnitOfWork(db)
    health_service = HealthService(uow)
    health = await health_service.get_runtime_health(runtime_id)
    return RuntimeHealthResponse(**health)


@router.get("/{runtime_id}/metrics", response_model=dict)
async def get_runtime_metrics(
    runtime_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    hours: Annotated[int, Query(ge=1, le=168)] = 24,
    db: AsyncSession = Depends(get_session),
) -> dict:
    uow = UnitOfWork(db)
    from app.services.observability import ObservabilityService

    obs_service = ObservabilityService(uow)
    summary = await obs_service.get_observability_summary(runtime_id, hours=hours)
    return summary


@router.get("/{runtime_id}/logs", response_model=list[RuntimeBuildLogRead])
async def list_runtime_logs(
    runtime_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> list[RuntimeBuildLogRead]:
    import uuid
    rid = uuid.UUID(runtime_id)
    result = await db.execute(
        select(RuntimeBuildLog).where(RuntimeBuildLog.runtime_id == rid).order_by(RuntimeBuildLog.created_at.asc())
    )
    logs = result.scalars().all()
    return [
        RuntimeBuildLogRead(
            id=l.id,
            runtime_id=l.runtime_id,
            stage=l.stage,
            status=l.status,
            started_at=l.started_at,
            completed_at=l.completed_at,
            error_message=l.error_message,
            metadata=l.metadata_,
            created_at=l.created_at,
            updated_at=l.updated_at,
        )
        for l in logs
    ]


@router.get("/{runtime_id}/chunks", response_model=list[RuntimeBuildChunkRead])
async def list_runtime_chunks(
    runtime_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> list[RuntimeBuildChunkRead]:
    import uuid
    from app.models.runtimes import RuntimeBuildChunk
    rid = uuid.UUID(runtime_id)
    result = await db.execute(
        select(RuntimeBuildChunk).where(RuntimeBuildChunk.runtime_id == rid)
    )
    chunks = result.scalars().all()
    return [
        RuntimeBuildChunkRead(
            id=c.id,
            runtime_id=c.runtime_id,
            document_id=c.document_id,
            chunk_index=c.chunk_index,
            action=c.action,
            embedded=c.embedded,
            indexed=c.indexed,
            embedding_hash=c.embedding_hash,
            metadata=c.metadata_,
            created_at=c.created_at,
            updated_at=c.updated_at,
        )
        for c in chunks
    ]


@router.delete("/{runtime_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_runtime(
    runtime_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> None:
    uow = UnitOfWork(db)
    service = RuntimeService(uow)
    await service.delete(runtime_id)
