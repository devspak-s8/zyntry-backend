from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


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


class OnboardingCompleteRequest(BaseModel):
    session_id: str
    runtime_name: str | None = None
    environment: str = "development"


class OnboardingCompleteResponse(BaseModel):
    session_id: str
    runtime_id: str
    runtime_name: str
    environment: str
    status: str
    enabled_integrations: list[dict[str, Any]]
    message: str
