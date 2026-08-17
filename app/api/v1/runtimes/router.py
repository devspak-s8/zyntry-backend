from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.api.v1.dependencies_tenant import require_project_membership
from app.api.v1.features.dependencies import require_feature
from app.api.v1.invoke.router import InvokeRequest, InvokeResponse, invoke
from app.core.database import get_session
from app.models.runtimes import RuntimeBuildLog
from app.models.users import User
from app.repositories import UnitOfWork
from app.schemas.apikeys import ApiKeyCreate, ApiKeyCreateResponse
from app.schemas.integrations import (
    RuntimeIntegrationCreate,
    RuntimeIntegrationRead,
    RuntimeIntegrationUpdate,
)
from app.schemas.runtimes import (
    RuntimeBuildChunkRead,
    RuntimeBuildLogRead,
    RuntimeCreate,
    RuntimeHealthResponse,
    RuntimeRead,
    RuntimeUpdate,
)
from app.services.apikeys import ApiKeyService
from app.services.health import HealthService
from app.services.integrations.service import IntegrationService
from app.services.runtimes import RuntimeService

router = APIRouter(prefix="/runtimes", tags=["runtimes"])
OBSERVABILITY_GUARD = [Depends(require_feature("observability"))]


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
    # User-first listing
    user_runtimes = await service.list_by_user(current_user.id)
    if user_runtimes:
        return [RuntimeRead(**r) for r in user_runtimes]
    runtimes = await uow.runtimes.list_active()
    return [RuntimeRead(**service._to_read(r)) for r in runtimes]


@router.post("", response_model=RuntimeRead, status_code=status.HTTP_201_CREATED)
async def create_runtime(
    body: RuntimeCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> RuntimeRead:
    uow = UnitOfWork(db)
    service = RuntimeService(uow)
    runtime = await service.get_or_create(body, default_user_id=current_user.id)
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


@router.post("/{runtime_id}/api-keys", response_model=ApiKeyCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_runtime_api_key(
    runtime_id: str,
    body: ApiKeyCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> ApiKeyCreateResponse:
    try:
        rid = uuid.UUID(runtime_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid runtime_id format") from None

    uow = UnitOfWork(db)
    runtime = await uow.runtimes.get(rid)
    if runtime is None:
        raise HTTPException(status_code=404, detail="Runtime not found")
    if runtime.user_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Unauthorized to create API keys for this runtime")

    service = ApiKeyService(db)
    body.runtime_id = rid
    if not body.environment:
        body.environment = runtime.environment
    result = await service.create_key(
        user_id=current_user.id,
        data=body,
        organization_id=runtime.organization_id,
    )
    return ApiKeyCreateResponse(
        **result["api_key"].model_dump(),
        key=result["raw_key"],
    )


@router.get("/{runtime_id}/integrations", response_model=list[RuntimeIntegrationRead])
async def list_runtime_integrations(
    runtime_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> list[RuntimeIntegrationRead]:
    try:
        rid = uuid.UUID(runtime_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid runtime_id format") from None

    uow = UnitOfWork(db)
    service = IntegrationService(uow)
    items = await service.list_runtime_integrations(rid)
    return [
        RuntimeIntegrationRead(
            id=i.id,
            runtime_id=i.runtime_id,
            integration_slug=i.integration_slug,
            connection_mode=i.connection_mode,
            enabled_capabilities=i.enabled_capabilities or [],
            is_enabled=i.is_enabled,
            connection_required=i.connection_required,
            connection_status=i.connection_status,
            connection_id=i.connection_id,
            config=i.config or {},
            created_at=i.created_at,
            updated_at=i.updated_at,
        )
        for i in items
    ]


@router.post("/{runtime_id}/integrations", response_model=RuntimeIntegrationRead, status_code=status.HTTP_201_CREATED)
async def enable_runtime_integration(
    runtime_id: str,
    body: RuntimeIntegrationCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> RuntimeIntegrationRead:
    try:
        rid = uuid.UUID(runtime_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid runtime_id format") from None

    uow = UnitOfWork(db)
    runtime = await uow.runtimes.get(rid)
    if runtime is None:
        raise HTTPException(status_code=404, detail="Runtime not found")
    if runtime.user_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Unauthorized")

    service = IntegrationService(uow)
    try:
        item = await service.enable_runtime_integration(rid, body)
        return RuntimeIntegrationRead(
            id=item.id,
            runtime_id=item.runtime_id,
            integration_slug=item.integration_slug,
            connection_mode=item.connection_mode,
            enabled_capabilities=item.enabled_capabilities or [],
            is_enabled=item.is_enabled,
            connection_required=item.connection_required,
            connection_status=item.connection_status,
            connection_id=item.connection_id,
            config=item.config or {},
            created_at=item.created_at,
            updated_at=item.updated_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/{runtime_id}/integrations/{integration_slug}", response_model=RuntimeIntegrationRead)
async def update_runtime_integration(
    runtime_id: str,
    integration_slug: str,
    body: RuntimeIntegrationUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> RuntimeIntegrationRead:
    try:
        rid = uuid.UUID(runtime_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid runtime_id format") from None

    uow = UnitOfWork(db)
    service = IntegrationService(uow)
    try:
        item = await service.update_runtime_integration(rid, integration_slug, body)
        return RuntimeIntegrationRead(
            id=item.id,
            runtime_id=item.runtime_id,
            integration_slug=item.integration_slug,
            connection_mode=item.connection_mode,
            enabled_capabilities=item.enabled_capabilities or [],
            is_enabled=item.is_enabled,
            connection_required=item.connection_required,
            connection_status=item.connection_status,
            connection_id=item.connection_id,
            config=item.config or {},
            created_at=item.created_at,
            updated_at=item.updated_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{runtime_id}/integrations/{integration_slug}", status_code=status.HTTP_204_NO_CONTENT)
async def disable_runtime_integration(
    runtime_id: str,
    integration_slug: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> None:
    try:
        rid = uuid.UUID(runtime_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid runtime_id format") from None

    uow = UnitOfWork(db)
    service = IntegrationService(uow)
    await service.disable_runtime_integration(rid, integration_slug)


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


@router.post(
    "/{runtime_id}/console/invoke",
    response_model=InvokeResponse,
    dependencies=[Depends(require_feature("runtime_console"))],
)
async def invoke_runtime_console(
    runtime_id: str,
    body: InvokeRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> InvokeResponse:
    """Invoke a runtime from the authenticated browser console without exposing an API key."""
    try:
        runtime_uuid = uuid.UUID(runtime_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid runtime_id format") from None

    uow = UnitOfWork(db)
    runtime = await uow.runtimes.get(runtime_uuid)
    if runtime is None:
        raise HTTPException(status_code=404, detail="Runtime not found")

    if runtime.project_id:
        await require_project_membership(str(runtime.project_id), current_user, db)
    elif runtime.user_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Unauthorized access to runtime")

    safe_body = body.model_copy(
        update={
            "project": str(runtime.project_id) if runtime.project_id else None,
            "runtime_id": str(runtime.id),
        }
    )
    return await invoke(safe_body, current_user, db)


@router.post("/{runtime_id}/propagate", response_model=dict)
async def propagate_runtime(
    runtime_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> dict:
    uow = UnitOfWork(db)
    service = RuntimeService(uow)
    result = await service.enqueue_build(runtime_id, trigger="propagation")
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


@router.get("/{runtime_id}/health", response_model=RuntimeHealthResponse, dependencies=OBSERVABILITY_GUARD)
async def get_runtime_health(
    runtime_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> RuntimeHealthResponse:
    uow = UnitOfWork(db)
    health_service = HealthService(uow)
    health = await health_service.get_runtime_health(runtime_id)
    return RuntimeHealthResponse(**health)


@router.get("/{runtime_id}/metrics", response_model=dict, dependencies=OBSERVABILITY_GUARD)
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


@router.get("/{runtime_id}/logs", response_model=list[RuntimeBuildLogRead], dependencies=OBSERVABILITY_GUARD)
async def list_runtime_logs(
    runtime_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> list[RuntimeBuildLogRead]:
    try:
        rid = uuid.UUID(runtime_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid runtime_id format") from None
    uow = UnitOfWork(db)
    runtime = await uow.runtimes.get(rid)
    if runtime is None:
        raise HTTPException(status_code=404, detail="Runtime not found")
    if runtime.project_id:
        await require_project_membership(str(runtime.project_id), current_user, db)
    elif runtime.user_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Unauthorized")

    result = await db.execute(
        select(RuntimeBuildLog)
        .where(RuntimeBuildLog.runtime_id == rid)
        .order_by(RuntimeBuildLog.created_at.desc())
        .limit(250)
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


@router.get("/{runtime_id}/chunks", response_model=list[RuntimeBuildChunkRead], dependencies=OBSERVABILITY_GUARD)
async def list_runtime_chunks(
    runtime_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> list[RuntimeBuildChunkRead]:
    from app.models.runtimes import RuntimeBuildChunk
    try:
        rid = uuid.UUID(runtime_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid runtime_id format") from None
    uow = UnitOfWork(db)
    runtime = await uow.runtimes.get(rid)
    if runtime is None:
        raise HTTPException(status_code=404, detail="Runtime not found")
    if runtime.project_id:
        await require_project_membership(str(runtime.project_id), current_user, db)
    elif runtime.user_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Unauthorized")

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
