from __future__ import annotations

import uuid
from datetime import datetime
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

from app.schemas.organizations import ORMModel


class ApiKeyCreate(ORMModel):
    name: str = Field(min_length=1, max_length=255)
    project_id: uuid.UUID | None = None
    runtime_id: uuid.UUID | None = None
    environment: str = "development"
    scopes: list[str] = Field(default_factory=lambda: ["read", "write"], max_length=50)
    allowed_origins: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("allowed_origins")
    @classmethod
    def validate_allowed_origins(cls, values: list[str]) -> list[str]:
        """Accept explicit browser origins, never arbitrary URL/path patterns."""
        normalized: list[str] = []
        for value in values:
            origin = value.strip().rstrip("/")
            parsed = urlparse(origin)
            if (
                not origin
                or parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.path
                or parsed.params
                or parsed.query
                or parsed.fragment
                or parsed.username
                or parsed.password
                or "*" in origin
            ):
                raise ValueError("Allowed origins must be explicit http(s) origins without paths")
            normalized.append(origin)
        return list(dict.fromkeys(normalized))


class ApiKeyRead(ORMModel):
    id: uuid.UUID
    name: str
    prefix: str
    runtime_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    environment: str = "development"
    allowed_origins: list[str] = Field(default_factory=list)
    scopes: list[str]
    revoked: bool
    expires_at: datetime | None
    last_used_at: datetime | None
    usage_count: int
    usage_stats: dict
    created_at: datetime
    updated_at: datetime


class ApiKeyCreateResponse(ApiKeyRead):
    key: str


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
