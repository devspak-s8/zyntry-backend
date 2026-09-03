from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.api.v1.dependencies_tenant import require_project_membership
from app.core.database import get_session
from app.core.ws_events import emit_provider_updated
from app.events import NotificationEvent
from app.models.users import User
from app.repositories import UnitOfWork
from app.schemas.providers import (
    ProviderConnectionCreate,
    ProviderConnectionRead,
    ProviderConnectionUpdate,
    ProviderTestRequest,
)
from app.services.model_discovery import get_model_discovery
from app.services.notifications import enqueue_notification
from app.services.providers import ProviderService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/providers", tags=["providers"])


@router.post("/test-connection", tags=["providers"])
async def test_provider_connection(
    body: ProviderTestRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> dict:
    uow = UnitOfWork(db)
    service = ProviderService(uow)
    result = await service.test_connection(body.model_dump())
    return result


@router.post("/discover", tags=["providers"])
async def discover_provider_resources(
    body: dict,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> dict:
    uow = UnitOfWork(db)
    service = ProviderService(uow)
    result = await service.discover_resources(body)
    return result


@router.post("/{connection_id}/sync", tags=["providers"])
async def sync_provider(
    connection_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> dict:
    uow = UnitOfWork(db)
    connection = await uow.providers.get(connection_id)
    if connection is None:
        raise HTTPException(status_code=404, detail="Provider connection not found")
    if connection.project_id:
        await require_project_membership(str(connection.project_id), current_user, db)
    service = ProviderService(uow)
    result = await service.sync(connection_id)
    return result


@router.post("/{connection_id}/refresh", tags=["providers"])
async def refresh_provider_credentials(
    connection_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> dict:
    uow = UnitOfWork(db)
    connection = await uow.providers.get(connection_id)
    if connection is None:
        raise HTTPException(status_code=404, detail="Provider connection not found")
    if connection.project_id:
        await require_project_membership(str(connection.project_id), current_user, db)
    service = ProviderService(uow)
    result = await service.refresh(connection_id)
    return result


@router.get("/{connection_id}/health", tags=["providers"])
async def get_provider_health(
    connection_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> dict:
    uow = UnitOfWork(db)
    connection = await uow.providers.get(connection_id)
    if connection is None:
        raise HTTPException(status_code=404, detail="Provider connection not found")
    if connection.project_id:
        await require_project_membership(str(connection.project_id), current_user, db)
    service = ProviderService(uow)
    result = await service.get_health(connection_id)
    return result


@router.get("", response_model=list[ProviderConnectionRead])
async def list_provider_connections(
    current_user: Annotated[User, Depends(get_current_user)],
    project_id: str | None = None,
    db: AsyncSession = Depends(get_session),
) -> list[ProviderConnectionRead]:
    if project_id is not None:
        try:
            uuid.UUID(project_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid project_id format") from None
        await require_project_membership(project_id, current_user, db)
    uow = UnitOfWork(db)
    service = ProviderService(uow)
    connections = await service.list_providers(
        project_id, organization_id=str(current_user.organization_id) if not project_id else None
    )
    return [
        ProviderConnectionRead(
            id=c["id"],
            organization_id=None,
            project_id=project_id,
            provider_name=c["provider_name"],
            display_name=c.get("display_name"),
            status=c["status"],
            last_tested_at=c.get("last_tested_at"),
            is_active=bool(c.get("is_active", False)),
            created_at=c.get("created_at", ""),
            updated_at=c.get("created_at", ""),
        )
        for c in connections
    ]


@router.get("/with-models")
async def list_providers_with_models(
    current_user: Annotated[User, Depends(get_current_user)],
    project_id: str | None = None,
    db: AsyncSession = Depends(get_session),
) -> list[dict]:
    if project_id is not None:
        try:
            uuid.UUID(project_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid project_id format") from None
        await require_project_membership(project_id, current_user, db)
    uow = UnitOfWork(db)
    service = ProviderService(uow)
    connections = await service.list_providers(
        project_id, organization_id=str(current_user.organization_id) if not project_id else None
    )
    discovery = get_model_discovery()
    all_providers = await discovery.discover_all_models()
    provider_model_map = {p["name"]: p for p in all_providers}
    result = []
    for c in connections:
        p_data = provider_model_map.get(c["provider_name"], {})
        result.append(
            {
                "id": c["id"],
                "provider_name": c["provider_name"],
                "display_name": c.get("display_name")
                or p_data.get("display_name", c["provider_name"]),
                "status": c["status"],
                "connected": c["status"] == "active",
                "model_count": p_data.get("model_count", 0),
                "models": p_data.get("models", []),
            }
        )
    return result


@router.post("", status_code=status.HTTP_201_CREATED)
async def connect_provider(
    body: ProviderConnectionCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> dict:
    if body.project_id:
        await require_project_membership(body.project_id, current_user, db)
    if body.organization_id and str(body.organization_id) != str(current_user.organization_id):
        raise HTTPException(status_code=403, detail="Cannot connect a provider for another organization")
    uow = UnitOfWork(db)
    service = ProviderService(uow)
    api_key = body.api_key
    if not api_key:
        discovery = get_model_discovery()
        api_key = discovery._get_api_key(body.provider_name)
    org_id = body.organization_id or (
        str(current_user.organization_id) if current_user.organization_id else None
    )
    try:
        result = await service.connect(
            ProviderConnectionCreate(
                provider_name=body.provider_name,
                display_name=body.display_name,
                api_key=api_key,
                organization_id=org_id,
                project_id=body.project_id,
                config=body.config,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result.get("requires_oauth"):
        await emit_provider_updated(
            str(current_user.id),
            body.project_id or "",
            result["provider_name"],
            False,
        )
        return result
    response = ProviderConnectionRead(
        id=result["id"],
        organization_id=org_id,
        project_id=body.project_id,
        provider_name=result["provider_name"],
        display_name=result.get("display_name") or body.display_name,
        status=result["status"],
        last_tested_at=result.get("last_tested_at"),
        is_active=bool(result.get("is_active", False)),
        created_at=result.get("created_at") or "",
        updated_at=result.get("updated_at") or "",
    )
    if not result.get("requires_oauth"):
        try:
            event = NotificationEvent(
                event_type="provider.connected",
                recipient=current_user.email,
                data={
                    "provider": body.provider_name,
                    "source_name": body.display_name or body.provider_name,
                },
                category="general",
            )
            enqueue_notification(event)
        except Exception:
            logger.exception("Failed to enqueue provider connected email")
    await emit_provider_updated(
        str(current_user.id),
        body.project_id or "",
        result["provider_name"],
        True,
    )
    return response.model_dump()


@router.patch("/{connection_id}", response_model=ProviderConnectionRead)
async def update_provider_connection(
    connection_id: str,
    body: ProviderConnectionUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> ProviderConnectionRead:
    uow = UnitOfWork(db)
    existing = await uow.providers.get(connection_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Provider connection not found")
    if existing.project_id:
        await require_project_membership(str(existing.project_id), current_user, db)
    update_data = {
        k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None
    }
    if "api_key" in update_data:
        api_key = str(update_data.pop("api_key")).strip()
        if not api_key:
            raise HTTPException(status_code=400, detail="API key cannot be empty")
        test_result = await ProviderService(uow).test_connection(
            {"provider_name": existing.provider_name, "api_key": api_key}
        )
        if not test_result.get("success"):
            raise HTTPException(status_code=400, detail=test_result.get("message"))
        from app.core.security import hash_token
        from app.services.security.secrets import default_secret_manager
        update_data.update(
            {
                "encrypted_api_key": default_secret_manager.encrypt(api_key),
                "api_key_hash": hash_token(api_key),
                "status": "active",
                "is_active": True,
                "last_tested_at": datetime.now(UTC).isoformat(),
            }
        )
    updated = await uow.providers.update(existing, **update_data)
    await uow.commit()
    response = ProviderConnectionRead(
        id=str(updated.id),
        organization_id=str(updated.organization_id) if updated.organization_id else None,
        project_id=str(updated.project_id) if updated.project_id else None,
        provider_name=updated.provider_name,
        display_name=updated.display_name,
        status=updated.status,
        last_tested_at=updated.last_tested_at,
        is_active=updated.is_active,
        created_at=updated.created_at.isoformat() if updated.created_at else "",
        updated_at=updated.updated_at.isoformat() if updated.updated_at else "",
    )
    await emit_provider_updated(
        str(current_user.id),
        str(updated.project_id) if updated.project_id else "",
        updated.provider_name,
        updated.is_active,
    )
    return response


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_provider(
    connection_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> None:
    uow = UnitOfWork(db)
    connection = await uow.providers.get(connection_id)
    if connection:
        if connection.project_id:
            await require_project_membership(str(connection.project_id), current_user, db)
        project_id = str(connection.project_id) if connection.project_id else ""
        provider_name = connection.provider_name
        display_name = connection.display_name or provider_name
        await ProviderService(uow).disconnect(connection_id)
        await emit_provider_updated(str(current_user.id), project_id, provider_name, False)
        try:
            event = NotificationEvent(
                event_type="provider.disconnected",
                recipient=current_user.email,
                data={"provider": provider_name, "display_name": display_name},
                category="general",
            )
            enqueue_notification(event)
        except Exception:
            logger.exception("Failed to enqueue provider disconnected email")
