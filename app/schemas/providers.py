from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ProviderConnectionCreate(BaseModel):
    provider_name: str = Field(min_length=1, max_length=64)
    display_name: str | None = None
    api_key: str | None = Field(default=None, min_length=1)
    organization_id: str | None = None
    project_id: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class ProviderConnectionRead(BaseModel):
    id: str
    organization_id: str | None
    project_id: str | None
    provider_name: str
    display_name: str | None
    status: str
    last_tested_at: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ProviderConnectionUpdate(BaseModel):
    display_name: str | None = None
    api_key: str | None = None
    config: dict[str, Any] | None = None
    status: str | None = None
    is_active: bool | None = None


class ProviderTestRequest(BaseModel):
    provider_name: str
    api_key: str
