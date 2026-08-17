from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class IntegrationCapabilityRead(BaseModel):
    slug: str
    name: str
    description: str
    is_write: bool = False
    required_scopes: list[str] = Field(default_factory=list)
    permission_requirements: list[str] = Field(default_factory=list)


class IntegrationDefinitionRead(BaseModel):
    id: str
    slug: str
    name: str
    description: str
    category: str
    icon: str = ""
    enabled: bool = True
    supported_connection_modes: list[str] = Field(default_factory=list)
    authentication_methods: list[str] = Field(default_factory=list)
    capabilities: list[IntegrationCapabilityRead] = Field(default_factory=list)
    required_scopes: list[str] = Field(default_factory=list)
    documentation_url: str = ""
    configuration_schema: dict[str, Any] = Field(default_factory=dict)
    credential_requirements: dict[str, Any] = Field(default_factory=dict)
    health_check: dict[str, Any] = Field(default_factory=dict)
    version: str = "1.0.0"


class RuntimeIntegrationCreate(BaseModel):
    integration_slug: str
    connection_mode: str = "zyntry_managed"
    enabled_capabilities: list[str] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)


class RuntimeIntegrationUpdate(BaseModel):
    enabled_capabilities: list[str] | None = None
    is_enabled: bool | None = None
    config: dict[str, Any] | None = None


class RuntimeIntegrationRead(BaseModel):
    id: UUID
    runtime_id: UUID
    integration_slug: str
    connection_mode: str
    enabled_capabilities: list[str]
    is_enabled: bool
    connection_required: bool
    connection_status: str
    connection_id: UUID | None
    config: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class ConnectionAuthorizeRequest(BaseModel):
    runtime_id: str | None = None
    connection_mode: str = "zyntry_managed"  # "zyntry_managed" or "end_user_oauth"
    end_user_id: str | None = None           # for Mode B (BYO-User connection)
    display_name: str | None = None
    redirect_uri: str | None = None
    scopes: list[str] | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class ConnectionAuthorizeResponse(BaseModel):
    requires_authorization: bool
    url: str | None = None
    state: str | None = None
    integration_slug: str
    connection_mode: str
    connection_id: str | None = None


class ConnectionDirectCreate(BaseModel):
    integration_slug: str
    connection_mode: str = "zyntry_managed"
    runtime_id: str | None = None
    end_user_id: str | None = None
    display_name: str
    auth_method: str = "connection_string"  # "api_key", "connection_string", "credentials", "service_account"
    credentials: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict)


class IntegrationConnectionRead(BaseModel):
    id: UUID
    user_id: UUID | None
    runtime_id: UUID | None
    integration_slug: str
    connection_mode: str
    end_user_id: str | None
    display_name: str
    auth_method: str
    scopes: list[str]
    expires_at: datetime | None
    last_synchronized_at: datetime | None
    status: str
    health_status: str
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime
