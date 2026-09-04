from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.organizations import ORMModel


class WorkflowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    definition: dict = Field(default_factory=dict)
    project_id: uuid.UUID


class WorkflowUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    definition: dict | None = None
    status: str | None = None


class WorkflowRead(ORMModel):
    id: uuid.UUID
    name: str
    description: str | None
    definition: dict
    project_id: uuid.UUID
    status: str
    created_at: datetime
    updated_at: datetime


class WorkflowExecutionRead(ORMModel):
    id: uuid.UUID
    workflow_id: uuid.UUID
    project_id: uuid.UUID
    status: str
    input_data: dict | None
    output_data: dict | None
    error_message: str | None
    duration_ms: int | None
    created_at: datetime


class WorkflowRunRequest(BaseModel):
    workflow_id: uuid.UUID
    input_data: dict | None = None


class WorkflowValidateRequest(BaseModel):
    definition: dict


class WorkflowTestRequest(BaseModel):
    definition: dict
    input_data: dict | None = None


class WorkflowValidationResult(BaseModel):
    valid: bool
    errors: list[str]
    warnings: list[str]


class WorkflowTestResult(BaseModel):
    success: bool
    output: dict | None
    error: str | None
    duration_ms: int


class WorkflowSchedule(BaseModel):
    enabled: bool = False
    cron: str | None = Field(default=None, max_length=128)
    timezone: str = "UTC"
    input_data: dict[str, Any] = Field(default_factory=dict)


class WorkflowScheduleUpdate(WorkflowSchedule):
    pass


class WorkflowScheduleRead(WorkflowSchedule):
    workflow_id: uuid.UUID
    next_run_at: datetime | None = None
    last_run_at: datetime | None = None
