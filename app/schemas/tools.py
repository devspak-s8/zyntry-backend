from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ToolCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    schema: dict[str, Any] = Field(default_factory=dict)
    implementation: str | None = None
    project_id: str | None = None


class ToolRead(BaseModel):
    id: str
    name: str
    description: str | None
    schema: dict[str, Any]
    implementation: str | None
    project_id: str | None
    created_at: datetime
    updated_at: datetime


class ToolUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    schema: dict[str, Any] | None = None
    implementation: str | None = None
    is_active: bool | None = None
