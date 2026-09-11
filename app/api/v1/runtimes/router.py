from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.api.v1.dependencies_tenant import (
    require_organization_membership,
    require_project_membership,
    require_runtime_access,
)
from app.api.v1.features.dependencies import require_feature
from app.api.v1.invoke.router import InvokeRequest, InvokeResponse, invoke
from app.core.database import get_session
from app.models.events import Event
from app.models.integrations import RuntimeIntegration
from app.models.runtimes import Runtime, RuntimeBuildLog
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
    RuntimeNameCheckRequest,
    RuntimeNameCheckResponse,
    RuntimeRead,
    RuntimeSecurityIpRule,
    RuntimeSecurityPolicy,
    RuntimeTopologyResponse,
    RuntimeTopologySimulationRequest,
    RuntimeTopologySimulationResponse,
    RuntimeUpdate,
)
from app.services.apikeys import ApiKeyService
from app.services.health import HealthService
from app.services.integrations.definitions import integration_registry
from app.services.integrations.service import IntegrationService
from app.services.runtime_security import (
    RuntimeSecurityService,
    normalize_runtime_security_policy,
    persist_runtime_security_event,
)
from app.services.runtime_topology import build_runtime_topology
from app.services.runtimes import RuntimeCreationConflict, RuntimeService
from app.services.security.secrets import default_secret_manager

router = APIRouter(prefix="/runtimes", tags=["runtimes"])
OBSERVABILITY_GUARD = [Depends(require_feature("observability"))]
runtime_security_service = RuntimeSecurityService()


def _runtime_read(value: RuntimeRead | dict[str, Any]) -> RuntimeRead:
    """Convert a service projection into the typed HTTP response model."""
    if isinstance(value, RuntimeRead):
        return value
    return RuntimeRead.model_validate(value)


def _safe_integration_config(value: dict | None) -> dict:
    return default_secret_manager.redact(value or {})


def _runtime_integration_ui_config(item: RuntimeIntegration) -> dict:
    """Expose non-secret connection metadata needed by setup UIs.

    Runtime integration rows intentionally store only the selected policy. The
    auth/setup metadata lives in the canonical integration registry, so merge
    it into the response without persisting it on the runtime row. This keeps
    the project wizard from guessing that an OAuth connector needs a token
    input (or that every database is PostgreSQL).
    """
    config = _safe_integration_config(item.config)
    definition = integration_registry.get(item.integration_slug)
    if definition is None:
        return config

    definition_data = definition.to_dict()
    auth_methods = [str(method).lower() for method in definition.auth_methods]
    if "file_upload" in auth_methods:
        setup_kind = "document_upload"
    elif "public_url" in auth_methods:
        setup_kind = "web_crawler"
    elif definition.category in {"databases", "geospatial"}:
        setup_kind = "database"
    elif "mcp_config" in auth_methods or "stdio" in auth_methods or "sse" in auth_methods:
        setup_kind = "mcp"
    elif "oauth2" in auth_methods:
        setup_kind = "oauth"
    else:
        setup_kind = "credentials"

    # The registry is authoritative for how a connector is set up. Runtime
    # policy config may contain display names and connection requirements, but
    # stale planner output must not turn an OAuth connector into a token form
    # (or make a database look like PostgreSQL). Secret values are already
    # redacted before this metadata is merged.
    config["setup_kind"] = setup_kind
    config["auth_methods"] = definition_data.get("auth_methods", auth_methods)
    config["auth_type"] = "oauth2" if "oauth2" in auth_methods else auth_methods[0] if auth_methods else "credentials"
    config["connection_modes"] = definition.connection_modes
    config["supports_end_user_oauth"] = definition.supports_end_user_oauth
    config["supports_zyntry_managed"] = definition.supports_zyntry_managed
    config["configuration_schema"] = definition_data.get("configuration_schema", {})
    config["credential_requirements"] = definition.credential_requirements
    config["required_scopes"] = definition.scopes
    return config


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
        await require_project_membership(project_id, current_user, db)
        runtime = await service.get_by_project(project_id)
        return [_runtime_read(runtime)] if runtime else []
    if organization_id:
        await require_organization_membership(organization_id, current_user, db)
        return [_runtime_read(item) for item in await service.list_by_organization(organization_id)]

    # Include both directly owned runtimes and runtimes owned by the user's
    # organization. Project-created runtimes are organization-scoped as well,
    # so filtering only by user can make a valid runtime disappear from the
    # console after it is attached to a project.
    runtimes = await service.list_by_user(current_user.id)
    if current_user.organization_id:
        runtimes.extend(
            await service.list_by_organization(str(current_user.organization_id))
        )
    unique: dict[str, dict[str, Any]] = {str(runtime["id"]): runtime for runtime in runtimes}
    return [_runtime_read(runtime) for runtime in unique.values()]


@router.post("/name-check", response_model=RuntimeNameCheckResponse)
async def check_runtime_name(
    body: RuntimeNameCheckRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> RuntimeNameCheckResponse:
    """Check a runtime name and project binding without creating anything."""
    if body.project_id is not None:
        await require_project_membership(str(body.project_id), current_user, db)
    service = RuntimeService(UnitOfWork(db))
    result = await service.inspect_name(current_user.id, body.name, body.project_id)
    return RuntimeNameCheckResponse(**result)


@router.post("", response_model=RuntimeRead, status_code=status.HTTP_201_CREATED)
async def create_runtime(
    body: RuntimeCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> RuntimeRead:
    if body.project_id is not None:
        await require_project_membership(str(body.project_id), current_user, db)
    body = body.model_copy(
        update={
            "user_id": current_user.id,
            "organization_id": current_user.organization_id,
        }
    )
    uow = UnitOfWork(db)
    service = RuntimeService(uow)
    try:
        runtime = await service.get_or_create(body, default_user_id=current_user.id)
    except RuntimeCreationConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.as_detail()) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _runtime_read(runtime)


@router.get("/{runtime_id:uuid}", response_model=RuntimeRead)
async def get_runtime(
    runtime_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> RuntimeRead:
    uow = UnitOfWork(db)
    service = RuntimeService(uow)
    runtime_obj = await require_runtime_access(runtime_id, current_user, db)
    return _runtime_read(service._to_read(runtime_obj))


@router.get("/project/{project_id}", response_model=RuntimeRead)
async def get_runtime_by_project(
    project_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> RuntimeRead:
    try:
        uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project_id format") from None
    uow = UnitOfWork(db)
    service = RuntimeService(uow)
    await require_project_membership(project_id, current_user, db)
    runtime = await service.get_by_project(project_id)
    if not runtime:
        raise HTTPException(status_code=404, detail="Runtime not found")
    return _runtime_read(runtime)


@router.patch("/{runtime_id}", response_model=RuntimeRead)
async def update_runtime(
    runtime_id: str,
    body: RuntimeUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> RuntimeRead:
    try:
        rid = uuid.UUID(runtime_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid runtime_id format") from None

    uow = UnitOfWork(db)
    existing = await uow.runtimes.get(rid)
    if existing is None:
        raise HTTPException(status_code=404, detail="Runtime not found")
    if existing.project_id:
        await require_project_membership(str(existing.project_id), current_user, db)
    elif existing.user_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Unauthorized")

    service = RuntimeService(uow)
    try:
        runtime = await service.update(str(rid), body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if body.security_policies is not None:
        try:
            refreshed = await uow.runtimes.get(rid)
            if refreshed is not None:
                await persist_runtime_security_event(
                    db,
                    refreshed,
                    "policy_updated",
                    message="Runtime security policy updated.",
                )
                await db.commit()
        except Exception:
            pass
    return _runtime_read(runtime)


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

    runtime = await require_runtime_access(rid, current_user, db)

    config = dict(runtime.config or {})
    config["external_sources"] = body.model_dump()
    uow = UnitOfWork(db)
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

    runtime = await require_runtime_access(rid, current_user, db)

    service = ApiKeyService(db)
    # Runtime-scoped keys inherit the runtime's project and environment. A
    # caller must not mint a development key that can be presented to a
    # production runtime (or attach the key to a different project).
    body = body.model_copy(
        update={
            "runtime_id": rid,
            "project_id": runtime.project_id,
            "environment": runtime.environment or "development",
        }
    )
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
    await require_runtime_access(rid, current_user, db)
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
            config=_runtime_integration_ui_config(i),
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

    await require_runtime_access(rid, current_user, db)

    service = IntegrationService(UnitOfWork(db))
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
            config=_runtime_integration_ui_config(item),
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
    await require_runtime_access(rid, current_user, db)
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
            config=_runtime_integration_ui_config(item),
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
    await require_runtime_access(rid, current_user, db)
    await service.disable_runtime_integration(rid, integration_slug)


@router.post("/{runtime_id}/build", response_model=dict)
@router.post("/{runtime_id}/rebuild", response_model=dict, include_in_schema=False)
async def rebuild_runtime(
    runtime_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> dict:
    uow = UnitOfWork(db)
    service = RuntimeService(uow)
    await require_runtime_access(runtime_id, current_user, db)
    result = await service.enqueue_build(runtime_id, trigger="manual")
    return result


@router.get("/{runtime_id}/security", response_model=dict)
async def get_runtime_security_policy(
    runtime_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> dict:
    try:
        rid = uuid.UUID(runtime_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid runtime_id format") from None
    runtime = await require_runtime_access(rid, current_user, db)
    return {
        "runtime_id": str(runtime.id),
        "project_id": str(runtime.project_id) if runtime.project_id else None,
        "policy": normalize_runtime_security_policy(runtime.security_policies),
    }


@router.put("/{runtime_id}/security", response_model=dict)
async def update_runtime_security_policy(
    runtime_id: str,
    body: RuntimeSecurityPolicy,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> dict:
    try:
        rid = uuid.UUID(runtime_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid runtime_id format") from None
    runtime = await require_runtime_access(rid, current_user, db)
    try:
        policy = normalize_runtime_security_policy(
            {**(runtime.security_policies or {}), **body.model_dump()}
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await UnitOfWork(db).runtimes.update(runtime, security_policies=policy)
    try:
        await persist_runtime_security_event(
            db,
            runtime,
            "policy_updated",
            message="Runtime security policy updated.",
        )
    except Exception:
        # A history write must not make a valid policy update fail.
        pass
    await db.commit()
    return {
        "runtime_id": str(runtime.id),
        "project_id": str(runtime.project_id) if runtime.project_id else None,
        "policy": policy,
    }


@router.get("/{runtime_id}/security/events", response_model=list[dict])
async def list_runtime_security_events(
    runtime_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    """Return the selected runtime's redacted security event history."""
    try:
        rid = uuid.UUID(runtime_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid runtime_id format") from None
    runtime = await require_runtime_access(rid, current_user, db)
    scope_column = Event.project_id if runtime.project_id else Event.organization_id
    scope_value = runtime.project_id or runtime.organization_id
    stmt = (
        select(Event)
        .where(
            scope_column == scope_value,
            Event.event_type.like("runtime.security.%"),
        )
        .order_by(Event.created_at.desc())
    )
    result = await db.execute(stmt)
    records = [
        event for event in result.scalars().all()
        if str((event.data or {}).get("runtime_id")) == str(runtime.id)
    ]
    records = records[offset: offset + limit]
    return [
        {
            "id": str(event.id),
            "runtime_id": str(runtime.id),
            "event_type": event.event_type.removeprefix("runtime.security."),
            "created_at": event.created_at.isoformat() if event.created_at else None,
            **(event.data or {}),
        }
        for event in records
    ]


@router.post("/{runtime_id}/security/blocked-ips", response_model=dict)
async def block_runtime_ip(
    runtime_id: str,
    body: RuntimeSecurityIpRule,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Add a permanent IP/CIDR rule until an owner explicitly removes it."""
    try:
        rid = uuid.UUID(runtime_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid runtime_id format") from None
    runtime = await require_runtime_access(rid, current_user, db)
    try:
        candidate = normalize_runtime_security_policy({"blocked_ips": [body.ip]})["blocked_ips"][0]
    except (ValueError, IndexError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    current = normalize_runtime_security_policy(runtime.security_policies)
    if candidate not in current["blocked_ips"]:
        current["blocked_ips"].append(candidate)
    await UnitOfWork(db).runtimes.update(runtime, security_policies=current)
    await persist_runtime_security_event(
        db,
        runtime,
        "manual_ip_block",
        client_ip=candidate,
        code="ip_blocked",
        message="An IP rule was manually added to the runtime blocklist.",
    )
    await db.commit()
    return {"runtime_id": str(runtime.id), "policy": current}


@router.delete("/{runtime_id}/security/blocked-ips", response_model=dict)
async def unblock_runtime_ip(
    runtime_id: str,
    body: RuntimeSecurityIpRule,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Remove an IP/CIDR rule and clear any matching temporary Redis block."""
    try:
        rid = uuid.UUID(runtime_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid runtime_id format") from None
    runtime = await require_runtime_access(rid, current_user, db)
    try:
        candidate = normalize_runtime_security_policy({"blocked_ips": [body.ip]})["blocked_ips"][0]
    except (ValueError, IndexError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    current = normalize_runtime_security_policy(runtime.security_policies)
    current["blocked_ips"] = [item for item in current["blocked_ips"] if item != candidate]
    await UnitOfWork(db).runtimes.update(runtime, security_policies=current)
    await runtime_security_service.clear_ip_block(str(runtime.id), candidate)
    await persist_runtime_security_event(
        db,
        runtime,
        "manual_ip_unblock",
        client_ip=candidate,
        code="ip_unblocked",
        message="An IP rule was removed from the runtime blocklist.",
    )
    await db.commit()
    return {"runtime_id": str(runtime.id), "policy": current}


@router.post(
    "/{runtime_id}/console/invoke",
    response_model=InvokeResponse,
    dependencies=[Depends(require_feature("runtime_console"))],
)
async def invoke_runtime_console(
    runtime_id: str,
    body: InvokeRequest,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> InvokeResponse:
    """Invoke a runtime from the authenticated browser console without exposing an API key."""
    try:
        runtime_uuid = uuid.UUID(runtime_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid runtime_id format") from None

    runtime = await require_runtime_access(runtime_uuid, current_user, db)
    if runtime.project_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Attach this runtime to a project before invoking it",
        )

    safe_body = body.model_copy(
        update={
            "project": str(runtime.project_id) if runtime.project_id else None,
            "runtime_id": str(runtime.id),
            "stream": False,
        }
    )
    return cast(InvokeResponse, await invoke(safe_body, request, current_user, db))


@router.post("/{runtime_id}/propagate", response_model=dict)
async def propagate_runtime(
    runtime_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> dict:
    uow = UnitOfWork(db)
    service = RuntimeService(uow)
    await require_runtime_access(runtime_id, current_user, db)
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
    await require_runtime_access(runtime_id, current_user, db)
    result = await service.cancel(runtime_id)
    return result


async def _runtime_for_topology(runtime_id: str, current_user: User, db: AsyncSession) -> Runtime:
    try:
        rid = uuid.UUID(runtime_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid runtime_id format") from None
    return await require_runtime_access(rid, current_user, db)


async def _build_topology(runtime: Runtime, db: AsyncSession, *, simulation: str | None = None) -> dict:
    """Compatibility wrapper while callers migrate to the topology service."""
    return await build_runtime_topology(runtime, db, simulation=simulation)


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
    now = datetime.now(UTC)
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
    await require_runtime_access(runtime_id, current_user, db)
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
    try:
        rid = uuid.UUID(runtime_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid runtime_id format") from None
    await require_runtime_access(rid, current_user, db)
    uow = UnitOfWork(db)
    from app.services.observability import ObservabilityService

    obs_service = ObservabilityService(uow)
    summary = await obs_service.get_observability_summary(str(rid), hours=hours)
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
    await require_runtime_access(rid, current_user, db)

    result = await db.execute(
        select(RuntimeBuildLog)
        .where(RuntimeBuildLog.runtime_id == rid)
        .order_by(RuntimeBuildLog.created_at.desc())
        .limit(250)
    )
    logs = result.scalars().all()
    return [
        RuntimeBuildLogRead(
            id=log.id,
            runtime_id=log.runtime_id,
            stage=log.stage,
            status=log.status,
            started_at=log.started_at,
            completed_at=log.completed_at,
            error_message=log.error_message,
            metadata=log.metadata_,
            created_at=log.created_at,
            updated_at=log.updated_at,
        )
        for log in logs
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
    await require_runtime_access(rid, current_user, db)

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
    try:
        rid = uuid.UUID(runtime_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid runtime_id format") from None

    uow = UnitOfWork(db)
    existing = await uow.runtimes.get(rid)
    if existing is None:
        raise HTTPException(status_code=404, detail="Runtime not found")
    if existing.project_id:
        await require_project_membership(str(existing.project_id), current_user, db)
    elif existing.user_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Unauthorized")

    service = RuntimeService(uow)
    await service.delete(str(rid))
