from __future__ import annotations

import json
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.v1.dependencies import get_current_user
from app.core.database import get_session
from app.core.redis import redis_client
from app.emails import send_email
from app.models.organizations import Organization
from app.models.projects import Project
from app.models.users import User
from app.repositories import UnitOfWork
from app.schemas.projects import ProjectCreate, ProjectRead

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["projects"])


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

    await redis_client.set(cache_key, json.dumps([p.model_dump(mode="json") for p in projects]), ex=30)
    return projects


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> ProjectRead:
    org_id = body.organization_id or current_user.organization_id
    if org_id is None:
        raise HTTPException(status_code=400, detail="organization_id is required")
    if org_id != current_user.organization_id:
        raise HTTPException(status_code=403, detail="Cannot create project in another organization")

    org = await db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    existing = await db.execute(
        select(Project).where(
            Project.organization_id == org_id,
            Project.name == body.name,
        )
    )
    if existing.scalar_one_or_none() is not None:
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
        raise HTTPException(status_code=409, detail="Project with this slug already exists")
    except Exception as exc:
        await uow.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to create project: {exc}")

    await _invalidate_projects_cache(org_id)

    try:
        await send_email(
            "project_created",
            current_user.email,
            user_name=current_user.name,
            project_name=body.name,
        )
    except Exception:
        logger.exception("Failed to send project created email to %s", current_user.email)

    return ProjectRead(
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


@router.patch("/{project_id}", response_model=ProjectRead)
async def update_project(
    project_id: str,
    body: ProjectCreate,
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

    uow = UnitOfWork(db)
    try:
        await uow.projects.update(
            proj,
            name=body.name,
            slug=body.slug,
            description=body.description,
            settings=body.settings or {},
        )
        await uow.commit()
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
