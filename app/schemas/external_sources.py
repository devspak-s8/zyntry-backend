from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


ExternalStrategy = Literal[
    "internal_only",
    "internal_then_external",
    "external_then_internal",
    "parallel",
]


class ExternalSourcePolicy(BaseModel):
    enabled: bool = False
    strategy: ExternalStrategy = "internal_then_external"
    providers: list[str] = Field(default_factory=list)
    allowed_domains: list[str] = Field(default_factory=list)
    blocked_domains: list[str] = Field(default_factory=list)
    trusted_domains: list[str] = Field(default_factory=list)
    require_citations: bool = True
    source_validation: Literal["none", "standard", "strict"] = "standard"
    min_relevance: float = Field(default=0.5, ge=0.0, le=1.0)
    max_results: int = Field(default=5, ge=1, le=50)
    max_searches: int = Field(default=3, ge=1, le=20)
    timeout_seconds: int = Field(default=15, ge=1, le=120)
    fallback: Literal["strict", "best_effort", "internal_only"] = "best_effort"

    @field_validator("providers", "allowed_domains", "blocked_domains", "trusted_domains")
    @classmethod
    def normalize_values(cls, values: list[str]) -> list[str]:
        return sorted({value.strip().lower() for value in values if value.strip()})

