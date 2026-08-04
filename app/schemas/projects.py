from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.organizations import ORMModel


class ProjectCreate(ORMModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=255)
    description: str | None = None
    organization_id: uuid.UUID | None = None
    preset: str | None = None
    settings: dict = Field(default_factory=dict)


class ProjectRead(ORMModel):
    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    organization_id: uuid.UUID
    created_at: str
    settings: dict
    status: str
    connected_providers: list[str] = []
