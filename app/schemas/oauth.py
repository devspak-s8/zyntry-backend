from __future__ import annotations

from pydantic import BaseModel


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
    url: str
    state: str


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
