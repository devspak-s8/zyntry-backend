from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class UserRole(str, Enum):
    VIEWER = "viewer"
    DEVELOPER = "developer"
    ADMIN = "admin"
    OWNER = "owner"


class ActionType(str, Enum):
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    ADMIN = "admin"


class ToolDefinition(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    required_permission: UserRole = Field(default=UserRole.DEVELOPER)
    action_type: ActionType = Field(default=ActionType.READ)
    dangerous: bool = Field(default=False)


class ToolCall(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    status: str = Field(default="pending")
    result: Any | None = None
    error: str | None = None
    duration_ms: float | None = None
    timestamp: datetime | None = None


class AssistantMessage(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    role: str
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RuntimeContext(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    runtime_id: str
    project_id: str
    organization_id: str
    user_id: str
    user_role: UserRole
    runtime: dict[str, Any] = Field(default_factory=dict)
    providers: list[dict[str, Any]] = Field(default_factory=list)
    models: list[dict[str, Any]] = Field(default_factory=list)
    knowledge_sources: list[dict[str, Any]] = Field(default_factory=list)
    tools: list[dict[str, Any]] = Field(default_factory=list)
    logs: list[dict[str, Any]] = Field(default_factory=list)
    analytics: dict[str, Any] = Field(default_factory=dict)
    billing: dict[str, Any] = Field(default_factory=dict)
    health: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)
    security: dict[str, Any] = Field(default_factory=dict)
    deployment: dict[str, Any] = Field(default_factory=dict)


class RuntimeSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    runtime_id: str
    status: str
    health_score: float | None = None
    provider: str
    model: str
    embedding_model: str
    vector_store: str
    documents: int = 0
    chunks: int = 0
    embeddings: int = 0
    knowledge_sources_count: int = 0
    tools_count: int = 0
    last_build_completed: datetime | None = None
    last_propagated: datetime | None = None
    monthly_cost: float | None = None
    error_count: int = 0
    issues: list[str] = Field(default_factory=list)


class DiagnosticResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    issue: str
    severity: str
    description: str
    affected_components: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)


class OptimizationResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    category: str
    title: str
    description: str
    impact: str
    estimated_savings: str | None = None
    actions: list[str] = Field(default_factory=list)
    priority: str = "medium"


class PermissionCheck(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    allowed: bool
    required_role: UserRole
    user_role: UserRole
    reason: str | None = None


class RuntimeAction(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    required_permission: UserRole = Field(default=UserRole.DEVELOPER)


class AssistantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    message: str
    tool_calls: list[ToolCall] = Field(default_factory=list)
    diagnostics: list[DiagnosticResult] = Field(default_factory=list)
    optimizations: list[OptimizationResult] = Field(default_factory=list)
    context: RuntimeContext | None = None
    summary: RuntimeSummary | None = None
    streaming: bool = Field(default=False)
    metadata: dict[str, Any] = Field(default_factory=dict)
