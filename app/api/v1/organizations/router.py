from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.core.database import get_session
from app.models.organizations import Organization
from app.repositories import UnitOfWork
from app.schemas.organizations import OrganizationCreate, OrganizationRead
from app.models.users import User

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.get("", response_model=list[OrganizationRead])
async def list_organizations(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> list[OrganizationRead]:
    result = await db.execute(select(Organization))
    orgs = result.scalars().all()
    return [
        OrganizationRead(
            id=org.id,
            name=org.name,
            slug=org.slug,
            region="us-central1",
            created_at=org.created_at,
        )
        for org in orgs
    ]


@router.post("", response_model=OrganizationRead, status_code=status.HTTP_201_CREATED)
async def create_organization(
    body: OrganizationCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> OrganizationRead:
    uow = UnitOfWork(db)
    try:
        org = await uow.organizations.create(
            name=body.name,
            slug=body.slug,
        )
        current_user.organization_id = org.id
        await uow.commit()
    except IntegrityError:
        await uow.rollback()
        raise HTTPException(status_code=409, detail="Organization with this slug already exists")
    except Exception as exc:
        await uow.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to create organization: {exc}")

    return OrganizationRead(
        id=org.id,
        name=org.name,
        slug=org.slug,
        region="us-central1",
        created_at=org.created_at,
    )


@router.get("/{org_id}", response_model=OrganizationRead)
async def get_organization(
    org_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> OrganizationRead:
    import uuid
    try:
        oid = uuid.UUID(org_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid organization id")

    org = await db.get(Organization, oid)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    return OrganizationRead(
        id=org.id,
        name=org.name,
        slug=org.slug,
        region="us-central1",
        created_at=org.created_at,
    )


@router.patch("/{org_id}", response_model=OrganizationRead)
async def update_organization(
    org_id: str,
    body: OrganizationCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> OrganizationRead:
    import uuid
    try:
        oid = uuid.UUID(org_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid organization id")

    org = await db.get(Organization, oid)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    uow = UnitOfWork(db)
    try:
        await uow.organizations.update(org, name=body.name, slug=body.slug)
        await uow.commit()
    except IntegrityError:
        await uow.rollback()
        raise HTTPException(status_code=409, detail="Organization with this slug already exists")
    except Exception as exc:
        await uow.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to update organization: {exc}")

    return OrganizationRead(
        id=org.id,
        name=org.name,
        slug=org.slug,
        region="us-central1",
        created_at=org.created_at,
    )


@router.delete("/{org_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_organization(
    org_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> None:
    import uuid
    try:
        oid = uuid.UUID(org_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid organization id")

    org = await db.get(Organization, oid)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    uow = UnitOfWork(db)
    try:
        await uow.organizations.delete(org)
        await uow.commit()
    except Exception as exc:
        await uow.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete organization: {exc}")
