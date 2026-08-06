from __future__ import annotations

from pydantic import BaseModel


class ActionDefinition(BaseModel):
    name: str
    description: str
    provider: str
    parameters: dict[str, Any] = {}
    required_permissions: list[str] = []
    risk: str = "low"


class ActionRequest(BaseModel):
    provider: str
    action: str
    arguments: dict[str, Any] = {}
    confirm: bool = False


class ActionResponse(BaseModel):
    success: bool
    result: Any = None
    error: str | None = None
    execution_id: str | None = None


class ActionExecutionRead(BaseModel):
    id: str
    user_id: str
    project_id: str
    provider: str
    action: str
    arguments: dict[str, Any]
    result: Any = None
    error: str | None = None
    status: str
    duration_ms: int | None = None
    tokens_used: int
    cost: float
    created_at: str


class ActionConfirmationRead(BaseModel):
    id: str
    user_id: str
    project_id: str
    provider: str
    action: str
    arguments: dict[str, Any]
    risk: str
    status: str
    expires_at: str
    created_at: str
