from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


ConnectionOwnership = Literal["company", "end_user", "hybrid"]
MemoryScope = Literal["request", "session", "user", "organization"]


class ApplicationIntegrationRequirement(BaseModel):
    """An integration inferred from the application description."""

    slug: str = Field(min_length=1, max_length=64)
    purpose: str = Field(default="", max_length=500)
    ownership: ConnectionOwnership | None = None
    capabilities: list[str] = Field(default_factory=list)
    write_access: bool = False
    required: bool = True

    @field_validator("slug")
    @classmethod
    def normalize_slug(cls, value: str) -> str:
        return value.strip().lower().replace(" ", "_")

    @field_validator("capabilities")
    @classmethod
    def normalize_capabilities(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip().lower() for value in values if value.strip()))


class ApplicationRequirements(BaseModel):
    """Validated intermediate representation extracted from onboarding chat."""

    schema_version: Literal["1.0"] = "1.0"
    application_type: str | None = Field(default=None, max_length=128)
    primary_function: str | None = Field(default=None, max_length=1000)
    target_users: list[str] = Field(default_factory=list)
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)

    requires_ai: bool = True
    requires_documents: bool | None = None
    document_formats: list[str] = Field(default_factory=list)
    requires_external_data: bool | None = None
    external_source_types: list[str] = Field(default_factory=list)
    requires_tools: bool | None = None
    requires_memory: bool | None = None
    memory_scope: MemoryScope | None = None

    connection_ownership: ConnectionOwnership | None = None
    integrations: list[ApplicationIntegrationRequirement] = Field(default_factory=list)
    requested_actions: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    data_sensitivity: Literal["public", "internal", "confidential", "regulated"] | None = None
    expected_scale: Literal["prototype", "small", "medium", "large", "enterprise"] | None = None

    assumptions: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    extraction_source: Literal["model", "fallback", "hybrid"] = "fallback"

    @field_validator(
        "target_users",
        "inputs",
        "outputs",
        "document_formats",
        "external_source_types",
        "requested_actions",
        "constraints",
        "assumptions",
    )
    @classmethod
    def normalize_lists(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))

    def integration_slugs(self) -> list[str]:
        return list(dict.fromkeys(item.slug for item in self.integrations))

    def missing_requirements(self) -> list[str]:
        """Return only information that materially affects the runtime plan."""
        missing: list[str] = []
        if not self.application_type:
            missing.append("application_type")
        if not self.primary_function:
            missing.append("primary_function")
        if not self.target_users:
            missing.append("target_users")
        if not self.inputs:
            missing.append("inputs")
        if not self.outputs:
            missing.append("outputs")
        if self.requires_documents is None:
            missing.append("requires_documents")
        elif self.requires_documents and not self.document_formats:
            missing.append("document_formats")
        if self.requires_external_data is None:
            missing.append("requires_external_data")
        elif self.requires_external_data and not self.external_source_types:
            missing.append("external_source_types")
        if self.requires_tools is None:
            missing.append("requires_tools")
        elif self.requires_tools and not self.integrations:
            missing.append("integrations")
        if self.integrations and not self.connection_ownership:
            missing.append("connection_ownership")
        if self.requires_memory is None:
            missing.append("requires_memory")
        elif self.requires_memory and not self.memory_scope:
            missing.append("memory_scope")
        return missing

    def fingerprint(self) -> str:
        payload = self.model_dump(mode="json", exclude={"confidence", "extraction_source"})
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


class RuntimePlanComponent(BaseModel):
    key: str
    name: str
    enabled: bool = True
    reason: str
    configuration: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)


class RuntimePlan(BaseModel):
    """Versioned, reviewable plan generated from ApplicationRequirements."""

    schema_version: Literal["1.0"] = "1.0"
    plan_version: int = Field(default=1, ge=1)
    status: Literal["clarification_required", "draft", "validated"] = "draft"
    requirements_fingerprint: str
    application_type: str
    summary: str
    components: list[RuntimePlanComponent] = Field(default_factory=list)
    integration_policies: list[dict[str, Any]] = Field(default_factory=list)
    model_routing: dict[str, Any] = Field(default_factory=dict)
    security: dict[str, Any] = Field(default_factory=dict)
    observability: dict[str, Any] = Field(default_factory=dict)
    deployment: dict[str, Any] = Field(default_factory=dict)
    assumptions: list[str] = Field(default_factory=list)
    unresolved_requirements: list[str] = Field(default_factory=list)


class ClarificationQuestion(BaseModel):
    requirement: str
    question: str
    suggested_answers: list[str] = Field(default_factory=list)
