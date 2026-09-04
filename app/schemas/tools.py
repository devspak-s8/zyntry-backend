from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    schema: dict[str, Any] = Field(default_factory=dict)
    implementation: str | None = None
    project_id: str | None = None
    kind: Literal["http", "openapi", "database", "connector"] = "http"
    openapi_spec: dict[str, Any] | None = None
    read_only: bool = True
    database_type: str | None = None


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


class ToolCatalogItem(BaseModel):
    key: str
    name: str
    description: str
    category: str
    auth_type: str
    credential_fields: list[str] = Field(default_factory=list)
    config_fields: list[str] = Field(default_factory=list)


class ToolConnectRequest(BaseModel):
    project_id: str
    display_name: str | None = Field(default=None, max_length=255)
    config: dict[str, Any] = Field(default_factory=dict)
    credentials: dict[str, Any] = Field(default_factory=dict)


class OpenAPIToolCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    project_id: str
    server_url: str = Field(min_length=1, max_length=2048)
    spec: dict[str, Any] = Field(min_length=1)
    read_only: bool = True


class DatabaseToolCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    project_id: str
    database_type: str = Field(min_length=1, max_length=64)
    schema: dict[str, Any] = Field(default_factory=dict)
    read_only: bool = True


class ToolConnectionStatus(BaseModel):
    connector: str
    project_id: str
    connected: bool
    status: str
    message: str | None = None
    tool_id: str | None = None
    display_name: str | None = None
    tested_at: datetime | None = None
