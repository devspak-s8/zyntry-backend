from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class OnboardingStateCreate(BaseModel):
    organization_id: str | None = None
    project_id: str | None = None
    current_step: str = "welcome"
    completed_steps: list[str] = Field(default_factory=list)
    extra_data: dict[str, Any] = Field(default_factory=dict)


class OnboardingStateRead(BaseModel):
    id: str
    organization_id: str | None
    project_id: str | None
    user_id: str | None
    current_step: str
    completed_steps: list[str]
    extra_data: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class OnboardingStateUpdate(BaseModel):
    current_step: str | None = None
    completed_steps: list[str] | None = None
    extra_data: dict[str, Any] | None = None
