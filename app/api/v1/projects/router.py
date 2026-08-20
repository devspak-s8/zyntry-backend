from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.v1.dependencies import get_current_user
from app.api.v1.features.dependencies import require_feature
from app.core.database import get_session
from app.core.redis import redis_client
from app.events import NotificationEvent
from app.models.organizations import Organization
from app.models.projects import Project
from app.models.users import User
from app.repositories import UnitOfWork
from app.schemas.projects import ProjectConfigUpdate, ProjectCreate, ProjectRead, ProjectUpdate
from app.schemas.runtimes import RuntimeCreate, RuntimeRead
from app.services.notifications import publish_notification
from app.services.runtimes import RuntimeService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["projects"])


async def _deliver_project_created_email(event: NotificationEvent, project_id: uuid.UUID) -> bool:
    delivery = await publish_notification(event)
    email_delivery = delivery.get("email", {})
    if email_delivery.get("success"):
        logger.info("Project created email delivered", extra={"project_id": str(project_id)})
        return True
    logger.warning(
        "Project created email delivery failed",
        extra={"project_id": str(project_id), "delivery": email_delivery},
    )
    return False


def _to_read(p: Project) -> ProjectRead:
    return ProjectRead(
        id=p.id,
        name=p.name,
        slug=p.slug,
        description=p.description,
        organization_id=p.organization_id,
        created_at=p.created_at.isoformat() if p.created_at else "",
        settings=p.settings or {},
        status=p.status or "ready",
        connected_providers=[pr.name for pr in p.providers] if p.providers else [],
        hasBuiltRuntime=p.has_built_runtime,
    )


async def _invalidate_projects_cache(org_id: uuid.UUID) -> None:
    await redis_client.delete(f"projects:{org_id}")


async def _release_idempotency_lock(lock_key: str | None, token: str | None) -> None:
    if lock_key and token:
        await redis_client.eval(
            "if redis.call('get', KEYS[1]) == ARGV[1] then "
            "return redis.call('del', KEYS[1]) else return 0 end",
            1,
            lock_key,
            token,
        )


@router.get("", response_model=list[ProjectRead])
async def list_projects(
    current_user: Annotated[User, Depends(get_current_user)],
    organization_id: Annotated[str | None, Query()] = None,
    db: AsyncSession = Depends(get_session),
) -> list[ProjectRead]:
    if current_user.organization_id is None:
        return []

    cache_key = f"projects:{current_user.organization_id}"
    cached = await redis_client.get(cache_key)
    if cached:
        return [ProjectRead(**p) for p in json.loads(cached)]

    stmt = (
        select(Project)
        .where(Project.organization_id == current_user.organization_id)
        .options(selectinload(Project.providers))
        .order_by(Project.created_at.desc())
    )
    result = await db.execute(stmt)
    projects = [_to_read(p) for p in result.scalars().all()]

    await redis_client.set(
        cache_key, json.dumps([p.model_dump(mode="json") for p in projects]), ex=30
    )
    return projects


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ProjectRead:
    if idempotency_key is not None and not (1 <= len(idempotency_key) <= 255):
        raise HTTPException(status_code=400, detail="Invalid Idempotency-Key")

    idempotency_cache_key: str | None = None
    idempotency_lock_key: str | None = None
    lock_token: str | None = None
    request_hash = hashlib.sha256(
        body.model_dump_json(exclude_none=False).encode("utf-8")
    ).hexdigest()

    if idempotency_key:
        key_hash = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        idempotency_cache_key = f"idempotency:projects:{current_user.id}:{key_hash}"
        idempotency_lock_key = f"{idempotency_cache_key}:lock"

        cached = await redis_client.get(idempotency_cache_key)
        if cached:
            record = json.loads(cached)
            if record["request_hash"] != request_hash:
                raise HTTPException(
                    status_code=409,
                    detail="Idempotency-Key was already used with a different payload",
                )
            return ProjectRead(**record["response"])

        lock_token = uuid.uuid4().hex
        acquired = await redis_client.set(idempotency_lock_key, lock_token, nx=True, ex=30)
        if not acquired:
            for _ in range(100):
                await asyncio.sleep(0.05)
                cached = await redis_client.get(idempotency_cache_key)
                if cached:
                    record = json.loads(cached)
                    if record["request_hash"] != request_hash:
                        raise HTTPException(
                            status_code=409,
                            detail="Idempotency-Key was already used with a different payload",
                        )
                    return ProjectRead(**record["response"])
                if not await redis_client.exists(idempotency_lock_key):
                    break
            raise HTTPException(status_code=409, detail="Idempotent request is still processing")

    org_id = body.organization_id or current_user.organization_id
    if org_id is None:
        await _release_idempotency_lock(idempotency_lock_key, lock_token)
        raise HTTPException(status_code=400, detail="organization_id is required")
    if org_id != current_user.organization_id:
        await _release_idempotency_lock(idempotency_lock_key, lock_token)
        raise HTTPException(status_code=403, detail="Cannot create project in another organization")

    org = await db.get(Organization, org_id)
    if org is None:
        await _release_idempotency_lock(idempotency_lock_key, lock_token)
        raise HTTPException(status_code=404, detail="Organization not found")

    existing = await db.execute(
        select(Project).where(
            Project.organization_id == org_id,
            Project.name == body.name,
        )
    )
    if existing.scalar_one_or_none() is not None:
        await _release_idempotency_lock(idempotency_lock_key, lock_token)
        raise HTTPException(status_code=409, detail="Project with this name already exists")

    uow = UnitOfWork(db)
    try:
        proj = await uow.projects.create(
            name=body.name,
            slug=body.slug,
            description=body.description,
            organization_id=org_id,
            settings=body.settings or {},
            status="ready",
        )
        await uow.commit()
    except IntegrityError:
        await uow.rollback()
        await _release_idempotency_lock(idempotency_lock_key, lock_token)
        raise HTTPException(status_code=409, detail="Project with this slug already exists")
    except Exception as exc:
        await uow.rollback()
        await _release_idempotency_lock(idempotency_lock_key, lock_token)
        raise HTTPException(status_code=500, detail=f"Failed to create project: {exc}")

    await _invalidate_projects_cache(org_id)

    try:
        event = NotificationEvent(
            event_type="project.created",
            recipient=current_user.email,
            data={"user_name": current_user.name, "project_name": body.name},
            category="general",
        )
        await _deliver_project_created_email(event, proj.id)
    except Exception:
        logger.exception("Failed to deliver project created email to %s", current_user.email)

    response = ProjectRead(
        id=proj.id,
        name=proj.name,
        slug=proj.slug,
        description=proj.description,
        organization_id=proj.organization_id,
        created_at=proj.created_at.isoformat() if proj.created_at else "",
        settings=proj.settings or {},
        status=proj.status or "ready",
        connected_providers=[],
        hasBuiltRuntime=proj.has_built_runtime,
    )
    try:
        if idempotency_cache_key:
            await redis_client.set(
                idempotency_cache_key,
                json.dumps(
                    {
                        "request_hash": request_hash,
                        "response": response.model_dump(mode="json", by_alias=True),
                    }
                ),
                ex=86400,
            )
    finally:
        await _release_idempotency_lock(idempotency_lock_key, lock_token)
    return response


@router.get("/{project_id}", response_model=ProjectRead)
async def get_project(
    project_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> ProjectRead:
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project id")

    stmt = select(Project).where(Project.id == pid).options(selectinload(Project.providers))
    result = await db.execute(stmt)
    proj = result.scalar_one_or_none()

    if proj is None or proj.organization_id != current_user.organization_id:
        raise HTTPException(status_code=404, detail="Project not found")

    return _to_read(proj)


@router.post(
    "/{project_id}/runtime",
    response_model=RuntimeRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_feature("runtime_management"))],
)
async def create_project_runtime(
    project_id: str,
    body: RuntimeCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> RuntimeRead:
    """Create (or return) the runtime attached to a project.

    This project-scoped form mirrors ``POST /runtimes`` while deriving all
    ownership fields from the authenticated project instead of trusting them
    from the request body.
    """
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project id") from None

    proj = await db.get(Project, pid)
    if proj is None or proj.organization_id != current_user.organization_id:
        raise HTTPException(status_code=404, detail="Project not found")

    runtime_data = body.model_copy(
        update={
            "project_id": pid,
            "organization_id": proj.organization_id,
            "user_id": current_user.id,
        }
    )
    service = RuntimeService(UnitOfWork(db))
    runtime = await service.get_or_create(runtime_data, default_user_id=current_user.id)
    return RuntimeRead(**runtime)


@router.put("/{project_id}/config", response_model=dict)
async def configure_project(
    project_id: str,
    body: ProjectConfigUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> dict:
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project id") from None

    proj = await db.get(Project, pid)
    if proj is None or proj.organization_id != current_user.organization_id:
        raise HTTPException(status_code=404, detail="Project not found")

    uow = UnitOfWork(db)
    runtime = await uow.runtimes.get_by_project(pid)
    if runtime is None:
        raise HTTPException(
            status_code=409,
            detail="Attach a runtime before configuring the project",
        )

    config_data = body.model_dump(exclude_none=True)
    runtime_config = {**(runtime.config or {}), **config_data}
    runtime_updates = {
        "provider": body.provider,
        "model": body.model,
        "routing_strategy": body.routing_strategy,
        "system_instructions": body.system_instructions,
        "security_policies": body.security_settings,
        "config": runtime_config,
    }
    project_settings = {**(proj.settings or {}), **config_data}

    try:
        await uow.runtimes.update(runtime, **runtime_updates)
        await uow.projects.update(proj, settings=project_settings)
        await uow.commit()
    except Exception as exc:
        await uow.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to configure project: {exc}") from exc

    await _invalidate_projects_cache(proj.organization_id)
    return {
        "project_id": str(proj.id),
        "runtime_id": str(runtime.id),
        "config": config_data,
    }


@router.post("/{project_id}/build", response_model=dict)
async def build_project_runtime(
    project_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> dict:
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project id") from None

    proj = await db.get(Project, pid)
    if proj is None or proj.organization_id != current_user.organization_id:
        raise HTTPException(status_code=404, detail="Project not found")

    uow = UnitOfWork(db)
    runtime = await uow.runtimes.get_by_project(pid)
    if runtime is None:
        raise HTTPException(status_code=409, detail="Attach a runtime before building the project")

    return await RuntimeService(uow).enqueue_build(str(runtime.id), trigger="project_wizard")


@router.patch("/{project_id}", response_model=ProjectRead)
async def update_project(
    project_id: str,
    body: ProjectUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> ProjectRead:
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project id")

    proj = await db.get(Project, pid)
    if proj is None or proj.organization_id != current_user.organization_id:
        raise HTTPException(status_code=404, detail="Project not found")

    update_data = body.model_dump(exclude_unset=True)
    runtime_requested = "runtime_id" in update_data
    runtime_id = update_data.pop("runtime_id", None)
    if update_data.get("name") is None and "name" in update_data:
        raise HTTPException(status_code=422, detail="name cannot be null")
    if update_data.get("slug") is None and "slug" in update_data:
        raise HTTPException(status_code=422, detail="slug cannot be null")
    if update_data.get("settings") is None and "settings" in update_data:
        update_data["settings"] = {}

    uow = UnitOfWork(db)
    try:
        if runtime_requested:
            if runtime_id is None:
                raise HTTPException(status_code=422, detail="runtime_id cannot be null")
            runtime = await uow.runtimes.get(runtime_id)
            if runtime is None or runtime.user_id != current_user.id:
                raise HTTPException(status_code=404, detail="Runtime not found")
            if runtime.project_id not in (None, pid):
                raise HTTPException(
                    status_code=409,
                    detail="Runtime is attached to another project",
                )
            attached = await uow.runtimes.get_by_project(pid)
            if attached is not None and attached.id != runtime.id:
                raise HTTPException(status_code=409, detail="Project already has another runtime")
            await uow.runtimes.update(
                runtime,
                project_id=pid,
                organization_id=proj.organization_id,
            )
        if update_data:
            await uow.projects.update(proj, **update_data)
        await uow.commit()
    except HTTPException:
        await uow.rollback()
        raise
    except IntegrityError:
        await uow.rollback()
        raise HTTPException(status_code=409, detail="Project with this slug already exists")
    except Exception as exc:
        await uow.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to update project: {exc}")

    await _invalidate_projects_cache(proj.organization_id)

    stmt = select(Project).where(Project.id == pid).options(selectinload(Project.providers))
    result = await db.execute(stmt)
    updated_proj = result.scalar_one_or_none()
    if updated_proj is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return _to_read(updated_proj)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> None:
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project id")

    proj = await db.get(Project, pid)
    if proj is None or proj.organization_id != current_user.organization_id:
        raise HTTPException(status_code=404, detail="Project not found")

    org_id = proj.organization_id
    uow = UnitOfWork(db)
    try:
        await uow.projects.delete(proj)
        await uow.commit()
    except Exception as exc:
        await uow.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete project: {exc}")

    await _invalidate_projects_cache(org_id)
