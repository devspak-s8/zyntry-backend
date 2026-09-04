from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.onboarding_intelligence import (
    ApplicationRequirements,
    ClarificationQuestion,
    RuntimePlan,
)


class OnboardingSessionCreate(BaseModel):
    initial_prompt: str | None = None
    reset: bool = False


class OnboardingSessionRead(BaseModel):
    id: UUID
    user_id: UUID
    state: str
    messages: list[dict[str, Any]]
    configuration: dict[str, Any]
    suggested_actions: list[str] = Field(default_factory=list)
    is_complete: bool = False
    created_runtime_id: UUID | None = None
    created_api_key_id: UUID | None = None
    completed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    application_requirements: ApplicationRequirements | None = None
    runtime_plan: RuntimePlan | None = None
    clarification_question: ClarificationQuestion | None = None


class OnboardingMessageRequest(BaseModel):
    session_id: str
    message: str


class OnboardingMessageResponse(BaseModel):
    session_id: str
    response: str
    state: str
    configuration: dict[str, Any]
    is_complete: bool = False
    suggested_actions: list[str] = Field(default_factory=list)
    proposed_runtime: dict[str, Any] | None = None
    application_requirements: ApplicationRequirements | None = None
    runtime_plan: RuntimePlan | None = None
    clarification_question: ClarificationQuestion | None = None


class OnboardingCompleteRequest(BaseModel):
    session_id: str
    runtime_name: str | None = None
    environment: str = "development"
    integration_modes: dict[str, str] = Field(default_factory=dict)
    # A name conflict/mismatch is intentionally a two-step operation. The
    # first completion request returns a reviewable 409; the client must send
    # this acknowledgement after the user chooses the name to keep.
    name_reviewed: bool = False


class OnboardingCompleteResponse(BaseModel):
    session_id: str
    runtime_id: str | None = None
    runtime_name: str
    environment: str
    status: str
    enabled_integrations: list[dict[str, Any]]
    message: str
    application_requirements: ApplicationRequirements | None = None
    runtime_plan: RuntimePlan | None = None
