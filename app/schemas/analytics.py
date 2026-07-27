from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class UsageEventCreate(BaseModel):
    metric: str = Field(min_length=1, max_length=64)
    quantity: float = 0
    model: str | None = None
    provider: str | None = None
    project_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class UsageEventRead(BaseModel):
    id: str
    metric: str
    quantity: float
    model: str | None
    provider: str | None
    project_id: str | None
    metadata: dict[str, Any]
    created_at: datetime


class UsageSummary(BaseModel):
    total_requests: int
    total_tokens: int
    total_cost_cents: int
    avg_latency_ms: float
    error_count: int
    provider_breakdown: dict[str, int]
    model_breakdown: dict[str, int]
