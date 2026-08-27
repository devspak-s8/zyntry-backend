from __future__ import annotations

import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.api.v1.dependencies_tenant import require_project_membership
from app.api.v1.features.dependencies import require_feature
from app.api.v1.invoke.router import InvokeRequest, InvokeResponse, invoke
from app.core.database import get_session
from app.models.billing import UsageLog
from app.models.request_logs import RequestLog
from app.models.runtimes import Runtime, RuntimeBuildLog
from app.models.integrations import RuntimeIntegration
from app.models.users import User
from app.repositories import UnitOfWork
from app.schemas.apikeys import ApiKeyCreate, ApiKeyCreateResponse
from app.schemas.external_sources import ExternalSourcePolicy
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
    RuntimeTopologyEdge,
    RuntimeTopologyNode,
    RuntimeTopologyResponse,
    RuntimeTopologySimulationRequest,
    RuntimeTopologySimulationResponse,
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

    # Include both directly owned runtimes and runtimes owned by the user's
    # organization. Project-created runtimes are organization-scoped as well,
    # so filtering only by user can make a valid runtime disappear from the
    # console after it is attached to a project.
    runtimes = await service.list_by_user(current_user.id)
    if current_user.organization_id:
        runtimes.extend(
            await service.list_by_organization(str(current_user.organization_id))
        )
    unique: dict[str, dict] = {str(runtime["id"]): runtime for runtime in runtimes}
    return [RuntimeRead(**runtime) for runtime in unique.values()]


@router.post("", response_model=RuntimeRead, status_code=status.HTTP_201_CREATED)
async def create_runtime(
    body: RuntimeCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> RuntimeRead:
    uow = UnitOfWork(db)
    service = RuntimeService(uow)
    try:
        runtime = await service.get_or_create(body, default_user_id=current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return RuntimeRead(**runtime)


@router.get("/{runtime_id:uuid}", response_model=RuntimeRead)
async def get_runtime(
    runtime_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> RuntimeRead:
    uow = UnitOfWork(db)
    service = RuntimeService(uow)
    runtime = await service.get(str(runtime_id))
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


@router.put("/{runtime_id}/external-sources", response_model=ExternalSourcePolicy)
async def configure_external_sources(
    runtime_id: str,
    body: ExternalSourcePolicy,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> ExternalSourcePolicy:
    """Persist the runtime's external knowledge/retrieval policy."""
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

    config = dict(runtime.config or {})
    config["external_sources"] = body.model_dump()
    await uow.runtimes.update(runtime, config=config)
    await uow.commit()
    return body


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


async def _runtime_for_topology(runtime_id: str, current_user: User, db: AsyncSession) -> Runtime:
    try:
        rid = uuid.UUID(runtime_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid runtime_id format") from None
    runtime = await db.scalar(select(Runtime).where(Runtime.id == rid))
    if runtime is None:
        raise HTTPException(status_code=404, detail="Runtime not found")
    if runtime.project_id:
        await require_project_membership(str(runtime.project_id), current_user, db)
    elif runtime.user_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Unauthorized access to runtime")
    return runtime


async def _build_topology(runtime: Runtime, db: AsyncSession, *, simulation: str | None = None) -> dict:
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=24)
    usage_rows = list((await db.execute(
        select(UsageLog).where(UsageLog.runtime_id == runtime.id, UsageLog.created_at >= since)
    )).scalars().all())
    request_rows = []
    if runtime.project_id:
        request_rows = list((await db.execute(
            select(RequestLog).where(RequestLog.project_id == runtime.project_id, RequestLog.created_at >= since)
        )).scalars().all())
    latencies = sorted(float(row.latency_ms) for row in usage_rows if row.latency_ms is not None)
    p95 = latencies[min(len(latencies) - 1, max(0, int(len(latencies) * 0.95) - 1))] if latencies else None
    total_requests = sum(int(row.requests or 1) for row in usage_rows)
    total_tokens = sum(int(row.input_tokens or 0) + int(row.output_tokens or 0) for row in usage_rows)
    total_cost = sum(float(row.cost or 0) for row in usage_rows)
    errors = sum(1 for row in request_rows if int(row.status or 0) >= 400)
    provider_counts = Counter(row.provider for row in usage_rows if row.provider)
    model_counts = Counter(row.model for row in usage_rows if row.model)
    integrations = list((await db.execute(
        select(RuntimeIntegration).where(RuntimeIntegration.runtime_id == runtime.id)
    )).scalars().all())

    telemetry = {
        "requests_24h": total_requests,
        "tokens_24h": total_tokens,
        "cost_24h": round(total_cost, 8),
        "errors_24h": errors,
        "error_rate": round(errors / max(1, len(request_rows)), 6),
        "average_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else None,
        "p95_latency_ms": p95,
        "providers": dict(provider_counts),
        "models": dict(model_counts),
    }

    node_status = {
        "application": "active",
        "runtime": runtime.status,
        "router": "active",
        "model": "active" if runtime.provider and runtime.model else "unconfigured",
        "knowledge": "ready" if runtime.embeddings or runtime.documents == 0 else "indexing",
        "vector_store": "active" if runtime.vector_store else "unconfigured",
    }
    simulated = simulation is not None
    if simulation == "postgres_degraded":
        node_status["vector_store"] = "degraded"
        node_status["knowledge"] = "degraded"
    elif simulation == "traffic_surge":
        node_status["application"] = "pressured"
        node_status["router"] = "balancing"
    elif simulation == "llm_failover":
        node_status["model"] = "failed_over"

    nodes = [
        RuntimeTopologyNode(id="application", kind="application", label="Your Application", status=node_status["application"], metrics={"requests_24h": total_requests, "error_rate": telemetry["error_rate"]}, simulated=simulated),
        RuntimeTopologyNode(id="runtime", kind="runtime", label=runtime.name, status=node_status["runtime"], health=float(runtime.health or 0), metrics={"documents": runtime.documents, "chunks": runtime.chunks, "embeddings": runtime.embeddings, "index_size": runtime.index_size}, simulated=simulated),
        RuntimeTopologyNode(id="router", kind="router", label="AI Router", status=node_status["router"], metrics={"strategy": runtime.routing_strategy, "p95_latency_ms": p95}, simulated=simulated),
        RuntimeTopologyNode(id="model", kind="model", label=f"{runtime.provider or 'Unassigned'} / {runtime.model or 'Unassigned'}", status=node_status["model"], metrics={"average_latency_ms": telemetry["average_latency_ms"], "requests_24h": provider_counts.get(runtime.provider, 0)}, metadata={"provider": runtime.provider, "model": runtime.model}, simulated=simulated),
        RuntimeTopologyNode(id="knowledge", kind="knowledge", label="Indexed Knowledge", status=node_status["knowledge"], metrics={"documents": runtime.documents, "chunks": runtime.chunks, "embeddings": runtime.embeddings}, simulated=simulated),
        RuntimeTopologyNode(id="vector_store", kind="vector_store", label=runtime.vector_store or "Vector Store", status=node_status["vector_store"], metrics={"index_size": runtime.index_size}, simulated=simulated),
    ]
    for integration in integrations:
        nodes.append(RuntimeTopologyNode(
            id=f"integration:{integration.integration_slug}", kind="integration", label=integration.integration_slug,
            status=integration.connection_status if integration.is_enabled else "disabled",
            metadata={"capabilities": integration.enabled_capabilities or [], "connection_mode": integration.connection_mode},
            simulated=simulated,
        ))

    edges = [
        RuntimeTopologyEdge(source="application", target="runtime"),
        RuntimeTopologyEdge(source="runtime", target="router"),
        RuntimeTopologyEdge(source="router", target="model", status="degraded" if simulation == "llm_failover" else "active"),
        RuntimeTopologyEdge(source="runtime", target="knowledge"),
        RuntimeTopologyEdge(source="knowledge", target="vector_store", status="degraded" if simulation == "postgres_degraded" else "active"),
    ]
    edges.extend(RuntimeTopologyEdge(source="router", target=f"integration:{item.integration_slug}") for item in integrations if item.is_enabled)
    fallback_models = list(runtime.fallback_models or [])
    if simulation == "llm_failover":
        for index, fallback in enumerate(fallback_models):
            node_id = f"fallback:{index}"
            nodes.append(RuntimeTopologyNode(id=node_id, kind="model", label=fallback, status="active", metadata={"fallback": True}, simulated=True))
            edges.append(RuntimeTopologyEdge(source="router", target=node_id, metadata={"selected": index == 0, "reason": "simulated primary failure"}))

    return {
        "runtime_id": runtime.id,
        "project_id": runtime.project_id,
        "generated_at": now,
        "window_seconds": 86400,
        "simulated": simulated,
        "nodes": nodes,
        "edges": edges,
        "routing": {
            "strategy": runtime.routing_strategy,
            "provider": runtime.provider,
            "model": runtime.model,
            "fallback_models": fallback_models,
            "failover_enabled": True,
            "simulation_mode": simulation,
        },
        "telemetry": telemetry,
    }


@router.get("/{runtime_id}/topology", response_model=RuntimeTopologyResponse, dependencies=OBSERVABILITY_GUARD)
async def get_runtime_topology(
    runtime_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> RuntimeTopologyResponse:
    runtime = await _runtime_for_topology(runtime_id, current_user, db)
    return RuntimeTopologyResponse.model_validate(await _build_topology(runtime, db))


@router.post("/{runtime_id}/topology/simulate", response_model=RuntimeTopologySimulationResponse, dependencies=OBSERVABILITY_GUARD)
async def simulate_runtime_topology(
    runtime_id: str,
    body: RuntimeTopologySimulationRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> RuntimeTopologySimulationResponse:
    runtime = await _runtime_for_topology(runtime_id, current_user, db)
    generated = await _build_topology(runtime, db, simulation=body.mode)
    now = datetime.now(timezone.utc)
    return RuntimeTopologySimulationResponse(
        **generated,
        simulation_id=uuid.uuid4(),
        expires_at=now + timedelta(minutes=10),
        production_traffic_affected=False,
    )


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
