from __future__ import annotations

from typing import Annotated, Any
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
from app.services.onboarding.engine import OnboardingNameMismatchError

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


def _to_legacy_state_read(state: dict[str, Any]) -> OnboardingStateRead:
    return OnboardingStateRead(**state)


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
        reset=body.reset,
    )
    return OnboardingSessionRead(**session_data)


@router.post("/reset", response_model=OnboardingSessionRead, status_code=status.HTTP_200_OK)
async def reset_onboarding_session(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> OnboardingSessionRead:
    uow = UnitOfWork(db)
    service = OnboardingService(uow)
    session_data = await service.create_chat_session(
        user_id=current_user.id,
        initial_prompt=None,
        reset=True,
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
    except OnboardingNameMismatchError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.as_detail()) from exc
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
    try:
        state = await service.get_or_create(data, current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid project_id or organization_id") from exc
    return _to_legacy_state_read(state)


@router.post("", response_model=OnboardingStateRead, status_code=status.HTTP_201_CREATED)
async def create_onboarding_state(
    body: OnboardingStateCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> OnboardingStateRead:
    uow = UnitOfWork(db)
    service = OnboardingService(uow)
    try:
        state = await service.get_or_create(body, current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid project_id or organization_id") from exc
    return _to_legacy_state_read(state)


@router.patch("/{state_id}", response_model=OnboardingStateRead)
async def update_onboarding_state(
    state_id: str,
    body: OnboardingStateUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> OnboardingStateRead:
    uow = UnitOfWork(db)
    service = OnboardingService(uow)
    try:
        state = await service.update(state_id, body, current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid onboarding state id") from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return _to_legacy_state_read(state)
