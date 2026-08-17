from __future__ import annotations

from typing import Any
from uuid import UUID

from app.repositories import UnitOfWork
from app.schemas.onboarding import OnboardingStateCreate, OnboardingStateUpdate
from app.schemas.onboarding_chat import (
    OnboardingCompleteRequest,
    OnboardingCompleteResponse,
    OnboardingMessageRequest,
    OnboardingMessageResponse,
)
from app.services.onboarding.engine import OnboardingEngine


class OnboardingService:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow
        self.engine = OnboardingEngine(uow)

    # Chat-Based Onboarding Methods (Primary flow)
    async def create_chat_session(
        self, user_id: UUID, initial_prompt: str | None = None, reset: bool = False
    ) -> dict[str, Any]:
        session = await self.engine.get_or_create_session(user_id, initial_prompt, reset=reset)
        suggested = self.engine.get_suggested_actions_for_state(session.state)
        return {
            "id": str(session.id),
            "user_id": str(session.user_id),
            "state": session.state,
            "messages": session.messages,
            "configuration": session.configuration,
            "suggested_actions": suggested,
            "is_complete": session.state == "completed",
            "created_runtime_id": str(session.created_runtime_id) if session.created_runtime_id else None,
            "created_api_key_id": str(session.created_api_key_id) if session.created_api_key_id else None,
            "completed_at": session.completed_at.isoformat() if session.completed_at else None,
            "created_at": session.created_at.isoformat() if session.created_at else None,
            "updated_at": session.updated_at.isoformat() if session.updated_at else None,
        }

    async def send_chat_message(self, user_id: UUID, req: OnboardingMessageRequest) -> OnboardingMessageResponse:
        return await self.engine.process_message(user_id, req)

    async def complete_chat_onboarding(self, user_id: UUID, req: OnboardingCompleteRequest) -> OnboardingCompleteResponse:
        return await self.engine.complete_onboarding(user_id, req)

    async def get_chat_session(self, session_id: UUID) -> dict[str, Any] | None:
        session = await self.uow.onboarding_sessions.get(session_id)
        if not session:
            return None
        suggested = self.engine.get_suggested_actions_for_state(session.state)
        return {
            "id": str(session.id),
            "user_id": str(session.user_id),
            "state": session.state,
            "messages": session.messages,
            "configuration": session.configuration,
            "suggested_actions": suggested,
            "is_complete": session.state == "completed",
            "created_runtime_id": str(session.created_runtime_id) if session.created_runtime_id else None,
            "created_api_key_id": str(session.created_api_key_id) if session.created_api_key_id else None,
            "completed_at": session.completed_at.isoformat() if session.completed_at else None,
            "created_at": session.created_at.isoformat() if session.created_at else None,
            "updated_at": session.updated_at.isoformat() if session.updated_at else None,
        }

    # Legacy Onboarding Methods (Backwards compatibility)
    async def get_or_create(self, data: OnboardingStateCreate) -> dict:
        existing = None
        if data.project_id:
            existing = await self.uow.onboarding.get_by_project(UUID(str(data.project_id)))
        elif data.organization_id:
            existing = await self.uow.onboarding.get_by_org(UUID(str(data.organization_id)))

        if existing:
            return {
                "id": str(existing.id),
                "current_step": existing.current_step,
                "completed_steps": existing.completed_steps,
                "extra_data": existing.extra_data,
            }

        created = await self.uow.onboarding.create(
            organization_id=UUID(str(data.organization_id)) if data.organization_id else None,
            project_id=UUID(str(data.project_id)) if data.project_id else None,
            current_step=data.current_step,
            completed_steps=data.completed_steps,
            extra_data=data.extra_data,
        )
        await self.uow.commit()
        return {
            "id": str(created.id),
            "current_step": created.current_step,
            "completed_steps": created.completed_steps,
            "extra_data": created.extra_data,
        }

    async def update(self, state_id: str, data: OnboardingStateUpdate) -> dict:
        existing = await self.uow.onboarding.session.get(
            self.uow.onboarding.__class__, state_id
        )
        if not existing:
            raise ValueError("Onboarding state not found")

        update_data = data.model_dump(exclude_unset=True)
        updated = await self.uow.onboarding.update(existing, **update_data)
        await self.uow.commit()
        return {
            "id": str(updated.id),
            "current_step": updated.current_step,
            "completed_steps": updated.completed_steps,
            "extra_data": updated.extra_data,
        }
