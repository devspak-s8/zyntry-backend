from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ConnectionPurpose = Literal["source", "tool", "both"]


class OAuthProviderRead(BaseModel):
    id: str
    name: str
    display_name: str
    scopes: list[str]
    is_enabled: bool


class OAuthConnectionRead(BaseModel):
    id: str
    provider: str
    display_name: str
    scope: str | None
    status: str
    expires_at: str | None
    created_at: str


class OAuthAuthorizeResponse(BaseModel):
    requires_authorization: bool = True
    url: str | None = None
    state: str | None = None
    provider: str | None = None
    purpose: ConnectionPurpose | None = None
    oauth_connection_id: str | None = None
    tool_id: str | None = None
    source_id: str | None = None


class OAuthAuthorizeRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=64)
    project_id: str
    purpose: ConnectionPurpose = "tool"
    redirect_uri: str | None = None
    display_name: str | None = Field(default=None, max_length=255)
    source_config: dict[str, Any] = Field(default_factory=dict)


class OAuthCallbackResponse(BaseModel):
    connection_id: str
    provider: str
    display_name: str
    scope: str | None


class OAuthTokenExchangeRequest(BaseModel):
    provider: str
    code: str
    state: str
    project_id: str | None = None
    purpose: ConnectionPurpose = "tool"
    display_name: str | None = Field(default=None, max_length=255)
    source_config: dict[str, Any] = Field(default_factory=dict)
