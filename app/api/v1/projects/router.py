from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.core.database import get_session
from app.models.organizations import Organization
from app.models.projects import Project
from app.repositories import UnitOfWork
from app.schemas.projects import ProjectCreate, ProjectRead
from app.models.users import User

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectRead])
async def list_projects(
    current_user: Annotated[User, Depends(get_current_user)],
    organization_id: Annotated[str | None, Query()] = None,
    db: AsyncSession = Depends(get_session),
) -> list[ProjectRead]:
    stmt = select(Project)
    if organization_id:
        import uuid
        try:
            oid = uuid.UUID(organization_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid organization id")
        stmt = stmt.where(Project.organization_id == oid)

    result = await db.execute(stmt)
    projects = result.scalars().all()
    return [
        ProjectRead(
            id=p.id,
            name=p.name,
            slug=p.slug,
            description=p.description,
            organization_id=p.organization_id,
            created_at=p.created_at.isoformat() if p.created_at else "",
            settings=p.settings or {},
            status=p.status or "ready",
        )
        for p in projects
    ]


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> ProjectRead:
    import uuid
    org_id = body.organization_id if hasattr(body, "organization_id") else None
    if org_id is None and current_user.organization_id:
        org_id = current_user.organization_id
    if org_id is None:
        raise HTTPException(status_code=400, detail="organization_id is required")

    org = await db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")

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

    return ProjectRead(
        id=proj.id,
        name=proj.name,
        slug=proj.slug,
        description=proj.description,
        organization_id=proj.organization_id,
        created_at=proj.created_at.isoformat() if proj.created_at else "",
        settings=proj.settings or {},
        status=proj.status or "ready",
    )


@router.get("/{project_id}", response_model=ProjectRead)
async def get_project(
    project_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> ProjectRead:
    import uuid
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project id")

    proj = await db.get(Project, pid)
    if proj is None:
        raise HTTPException(status_code=404, detail="Project not found")

    return ProjectRead(
        id=proj.id,
        name=proj.name,
        slug=proj.slug,
        description=proj.description,
        organization_id=proj.organization_id,
        created_at=proj.created_at.isoformat() if proj.created_at else "",
        settings=proj.settings or {},
        status=proj.status or "ready",
    )


@router.patch("/{project_id}", response_model=ProjectRead)
async def update_project(
    project_id: str,
    body: ProjectCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> ProjectRead:
    import uuid
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project id")

    proj = await db.get(Project, pid)
    if proj is None:
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

    return ProjectRead(
        id=proj.id,
        name=proj.name,
        slug=proj.slug,
        description=proj.description,
        organization_id=proj.organization_id,
        created_at=proj.created_at.isoformat() if proj.created_at else "",
        settings=proj.settings or {},
        status=proj.status or "ready",
    )


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> None:
    import uuid
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project id")

    proj = await db.get(Project, pid)
    if proj is None:
        raise HTTPException(status_code=404, detail="Project not found")

    uow = UnitOfWork(db)
    try:
        await uow.projects.delete(proj)
        await uow.commit()
    except Exception as exc:
        await uow.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete project: {exc}")
