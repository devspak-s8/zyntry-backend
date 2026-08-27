from __future__ import annotations

from typing import Any
from uuid import UUID

from app.models.onboarding import OnboardingState
from app.repositories import UnitOfWork
from app.schemas.onboarding import OnboardingStateCreate, OnboardingStateUpdate
from app.schemas.onboarding_chat import (
    OnboardingCompleteRequest,
    OnboardingCompleteResponse,
    OnboardingMessageRequest,
    OnboardingMessageResponse,
)
from app.schemas.onboarding_intelligence import ApplicationRequirements
from app.services.onboarding.engine import OnboardingEngine


class OnboardingService:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow
        self.engine = OnboardingEngine(uow)

    def _clarification_question(self, configuration: dict[str, Any] | None) -> Any:
        requirements_data = (configuration or {}).get("application_requirements")
        if not requirements_data:
            return None
        try:
            requirements = ApplicationRequirements.model_validate(requirements_data)
        except Exception:
            return None
        return self.engine.clarification_service.next_question(requirements)

    # Chat-Based Onboarding Methods (Primary flow)
    async def create_chat_session(
        self, user_id: UUID, initial_prompt: str | None = None, reset: bool = False
    ) -> dict[str, Any]:
        session = await self.engine.get_or_create_session(user_id, initial_prompt, reset=reset)
        suggested = self.engine.get_suggested_actions_for_state(
            session.state, session.configuration
        )
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
            "application_requirements": (session.configuration or {}).get("application_requirements"),
            "runtime_plan": (session.configuration or {}).get("runtime_plan"),
            "clarification_question": None if session.state == "completed" else self._clarification_question(session.configuration),
        }

    async def send_chat_message(self, user_id: UUID, req: OnboardingMessageRequest) -> OnboardingMessageResponse:
        return await self.engine.process_message(user_id, req)

    async def complete_chat_onboarding(self, user_id: UUID, req: OnboardingCompleteRequest) -> OnboardingCompleteResponse:
        return await self.engine.complete_onboarding(user_id, req)

    async def get_chat_session(self, session_id: UUID) -> dict[str, Any] | None:
        session = await self.uow.onboarding_sessions.get(session_id)
        if not session:
            return None
        suggested = self.engine.get_suggested_actions_for_state(
            session.state, session.configuration
        )
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
            "application_requirements": (session.configuration or {}).get("application_requirements"),
            "runtime_plan": (session.configuration or {}).get("runtime_plan"),
            "clarification_question": None if session.state == "completed" else self._clarification_question(session.configuration),
        }

    # Legacy Onboarding Methods (Backwards compatibility)
    @staticmethod
    def _serialize_state(state: OnboardingState) -> dict[str, Any]:
        return {
            "id": str(state.id),
            "organization_id": str(state.organization_id) if state.organization_id else None,
            "project_id": str(state.project_id) if state.project_id else None,
            "user_id": str(state.user_id) if state.user_id else None,
            "current_step": state.current_step,
            "completed_steps": state.completed_steps or [],
            "extra_data": state.extra_data or {},
            "created_at": state.created_at,
            "updated_at": state.updated_at,
        }

    async def get_or_create(self, data: OnboardingStateCreate, user_id: UUID) -> dict[str, Any]:
        project_id = UUID(str(data.project_id)) if data.project_id else None
        organization_id = UUID(str(data.organization_id)) if data.organization_id else None
        existing = None
        if project_id:
            existing = await self.uow.onboarding.get_by_project(project_id, user_id)
        elif organization_id:
            existing = await self.uow.onboarding.get_by_org(organization_id, user_id)
        else:
            existing = await self.uow.onboarding.get_account_state(user_id)

        if existing:
            return self._serialize_state(existing)

        created = await self.uow.onboarding.create(
            organization_id=organization_id,
            project_id=project_id,
            user_id=user_id,
            current_step=data.current_step,
            completed_steps=data.completed_steps,
            extra_data=data.extra_data,
        )
        await self.uow.commit()
        return self._serialize_state(created)

    async def update(
        self, state_id: str, data: OnboardingStateUpdate, user_id: UUID
    ) -> dict[str, Any]:
        existing = await self.uow.onboarding.get(UUID(state_id))
        if not existing:
            raise LookupError("Onboarding state not found")
        if existing.user_id not in (None, user_id):
            raise PermissionError("Unauthorized access to onboarding state")

        update_data = data.model_dump(exclude_unset=True)
        # States created before user ownership was persisted are claimed by the
        # authenticated caller on first update, preserving legacy progress.
        if existing.user_id is None:
            update_data["user_id"] = user_id
        updated = await self.uow.onboarding.update(existing, **update_data)
        await self.uow.commit()
        return self._serialize_state(updated)
