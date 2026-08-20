from __future__ import annotations

import uuid

from pydantic import Field

from app.schemas.organizations import ORMModel


class ProjectCreate(ORMModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=255)
    description: str | None = None
    organization_id: uuid.UUID | None = None
    preset: str | None = None
    settings: dict = Field(default_factory=dict)


class ProjectUpdate(ORMModel):
    """Fields that may be changed after a project has been created."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    slug: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    settings: dict | None = None


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
    hasBuiltRuntime: bool = Field(default=False, alias="has_built_runtime")
