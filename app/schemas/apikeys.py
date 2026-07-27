from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.organizations import ORMModel


class ApiKeyCreate(ORMModel):
    name: str = Field(min_length=1, max_length=255)
    project_id: uuid.UUID | None = None
    scopes: list[str] = Field(default_factory=lambda: ["read"], max_length=50)


class ApiKeyRead(ORMModel):
    id: uuid.UUID
    name: str
    prefix: str
    scopes: list[str]
    revoked: bool
    expires_at: datetime | None
    last_used_at: datetime | None
    usage_count: int
    usage_stats: dict
    created_at: datetime
    updated_at: datetime


class ApiKeyRotateResponse(BaseModel):
    api_key: ApiKeyRead
    raw_key: str


class ApiKeyExpireRequest(BaseModel):
    expires_at: datetime | None = None


class ApiKeyUsageResponse(ORMModel):
    api_key_id: uuid.UUID
    calls: int
    tokens: int
    errors: int
    period_start: datetime | None
    period_end: datetime | None


class ApiKeyScopeUpdate(BaseModel):
    scopes: list[str] = Field(min_length=1, max_length=50)
