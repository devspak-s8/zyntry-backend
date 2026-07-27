from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.core.database import get_session
from app.models.users import User
from app.repositories import UnitOfWork
from app.schemas.onboarding import OnboardingStateCreate, OnboardingStateRead, OnboardingStateUpdate
from app.services.onboarding import OnboardingService

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


@router.get("", response_model=OnboardingStateRead)
async def get_onboarding_state(
    current_user: Annotated[User, Depends(get_current_user)],
    project_id: str | None = None,
    organization_id: str | None = None,
    db: AsyncSession = Depends(get_session),
) -> OnboardingStateRead:
    uow = UnitOfWork(db)
    service = OnboardingService(uow)
    data = OnboardingStateCreate(
        project_id=project_id,
        organization_id=organization_id,
    )
    state = await service.get_or_create(data)
    return OnboardingStateRead(
        id=state["id"],
        organization_id=organization_id,
        project_id=project_id,
        user_id=str(current_user.id),
        current_step=state["current_step"],
        completed_steps=state["completed_steps"],
        extra_data=state["extra_data"],
        created_at="",
        updated_at="",
    )


@router.post("", response_model=OnboardingStateRead, status_code=status.HTTP_201_CREATED)
async def create_onboarding_state(
    body: OnboardingStateCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> OnboardingStateRead:
    uow = UnitOfWork(db)
    service = OnboardingService(uow)
    state = await service.get_or_create(body)
    return OnboardingStateRead(
        id=state["id"],
        organization_id=body.organization_id,
        project_id=body.project_id,
        user_id=str(current_user.id),
        current_step=state["current_step"],
        completed_steps=state["completed_steps"],
        metadata=state["metadata"],
        created_at="",
        updated_at="",
    )


@router.patch("/{state_id}", response_model=OnboardingStateRead)
async def update_onboarding_state(
    state_id: str,
    body: OnboardingStateUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> OnboardingStateRead:
    uow = UnitOfWork(db)
    service = OnboardingService(uow)
    state = await service.update(state_id, body)
    return OnboardingStateRead(
        id=state["id"],
        organization_id=None,
        project_id=None,
        user_id=str(current_user.id),
        current_step=state["current_step"],
        completed_steps=state["completed_steps"],
        metadata=state["metadata"],
        created_at="",
        updated_at="",
    )
