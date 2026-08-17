from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.core.database import get_session
from app.models.users import User
from app.repositories import UnitOfWork
from app.schemas.onboarding import OnboardingStateCreate, OnboardingStateRead, OnboardingStateUpdate
from app.schemas.onboarding_chat import (
    OnboardingCompleteRequest,
    OnboardingCompleteResponse,
    OnboardingMessageRequest,
    OnboardingMessageResponse,
    OnboardingSessionCreate,
    OnboardingSessionRead,
)
from app.services.onboarding import OnboardingService

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


# =========================================================
# Chat-Based Onboarding Endpoints (Primary Flow)
# =========================================================

@router.post("/session", response_model=OnboardingSessionRead, status_code=status.HTTP_201_CREATED)
async def create_or_resume_session(
    current_user: Annotated[User, Depends(get_current_user)],
    body: OnboardingSessionCreate = OnboardingSessionCreate(),
    db: AsyncSession = Depends(get_session),
) -> OnboardingSessionRead:
    uow = UnitOfWork(db)
    service = OnboardingService(uow)
    session_data = await service.create_chat_session(
        user_id=current_user.id,
        initial_prompt=body.initial_prompt,
    )
    return OnboardingSessionRead(**session_data)


@router.post("/message", response_model=OnboardingMessageResponse)
async def send_onboarding_message(
    body: OnboardingMessageRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> OnboardingMessageResponse:
    uow = UnitOfWork(db)
    service = OnboardingService(uow)
    try:
        return await service.send_chat_message(user_id=current_user.id, req=body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/session/{session_id}", response_model=OnboardingSessionRead)
async def get_onboarding_session(
    session_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> OnboardingSessionRead:
    try:
        sid = UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session_id format") from None

    uow = UnitOfWork(db)
    service = OnboardingService(uow)
    session = await service.get_chat_session(sid)
    if session is None:
        raise HTTPException(status_code=404, detail="Onboarding session not found")
    if session["user_id"] != str(current_user.id):
        raise HTTPException(status_code=403, detail="Unauthorized access to onboarding session")
    return OnboardingSessionRead(**session)


@router.post("/complete", response_model=OnboardingCompleteResponse)
async def complete_onboarding(
    body: OnboardingCompleteRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> OnboardingCompleteResponse:
    uow = UnitOfWork(db)
    service = OnboardingService(uow)
    try:
        return await service.complete_chat_onboarding(user_id=current_user.id, req=body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# =========================================================
# Legacy Onboarding Endpoints (Backward Compatibility)
# =========================================================

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
        created_at=None,
        updated_at=None,
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
        extra_data=state["extra_data"],
        created_at=None,
        updated_at=None,
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
        extra_data=state["extra_data"],
        created_at=None,
        updated_at=None,
    )
