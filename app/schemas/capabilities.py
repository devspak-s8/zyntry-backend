from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field, field_validator


class RoleCapabilities(BaseModel):
    """Permissions granted to one runtime role.

    Roles are stored in the runtime JSON configuration so existing runtimes do
    not need a database migration.  The backend remains the authority: clients
    cannot grant themselves a role through an invocation request.
    """

    can_invoke: bool = True
    can_read_sources: bool = True
    can_use_tools: bool = False
    can_write: bool = False
    allowed_sources: list[str] = Field(default_factory=list)


class RuntimeAccessPolicy(BaseModel):
    enabled: bool = True
    default_role: str = "developer"
    roles: dict[str, RoleCapabilities] = Field(default_factory=dict)

    @field_validator("default_role")
    @classmethod
    def normalize_default_role(cls, value: str) -> str:
        value = value.strip().lower()
        if not value:
            raise ValueError("default_role cannot be empty")
        return value


class RuntimeBudgetPolicy(BaseModel):
    enabled: bool = False
    max_request_usd: Decimal | None = Field(default=None, ge=0)
    monthly_limit_usd: Decimal | None = Field(default=None, ge=0)
    requests_per_minute: int | None = Field(default=None, ge=1, le=100_000)


class RuntimeCapabilitiesRead(BaseModel):
    runtime_id: uuid.UUID
    access_control: RuntimeAccessPolicy
    budgets: RuntimeBudgetPolicy
    feature_flags: dict[str, bool] = Field(default_factory=dict)


class RuntimeAccessPolicyUpdate(RuntimeAccessPolicy):
    pass


class RuntimeBudgetPolicyUpdate(RuntimeBudgetPolicy):
    pass


class SourceRecordSet(BaseModel):
    source: str = Field(min_length=1, max_length=128)
    records: list[dict[str, Any]] = Field(default_factory=list)


class CrossSourceJoinRequest(BaseModel):
    sources: list[SourceRecordSet] = Field(min_length=1, max_length=20)
    join_on: str | None = Field(default=None, min_length=1, max_length=128)
    limit: int = Field(default=100, ge=1, le=10_000)


class CrossSourceJoinResponse(BaseModel):
    sources: list[str]
    records: list[dict[str, Any]]
    matched_records: int
    join_on: str | None
    provenance: list[dict[str, Any]]


class EvaluationCase(BaseModel):
    id: str | None = None
    name: str = Field(min_length=1, max_length=255)
    input: str = Field(min_length=1, max_length=20_000)
    expected_contains: list[str] = Field(default_factory=list)
    expected_sources: list[str] = Field(default_factory=list)
    expected_citations: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvaluationCaseResult(BaseModel):
    case_id: str
    passed: bool
    score: float = Field(ge=0, le=1)
    checks: dict[str, bool] = Field(default_factory=dict)
    response: str | None = None


class EvaluationSuiteRead(BaseModel):
    runtime_id: uuid.UUID
    version: int
    cases: list[EvaluationCase]
    updated_at: str | None = None


class EvaluationSuiteUpdate(BaseModel):
    cases: list[EvaluationCase] = Field(max_length=500)


class EvaluationRunRequest(BaseModel):
    responses: dict[str, str] = Field(default_factory=dict)


class EvaluationRunResponse(BaseModel):
    runtime_id: uuid.UUID
    version: int
    total: int
    passed: int
    score: float = Field(ge=0, le=1)
    results: list[EvaluationCaseResult]
