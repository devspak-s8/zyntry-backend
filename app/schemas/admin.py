from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field
from typing import Any


class AdminStats(BaseModel):
    total_users: int
    total_organizations: int
    total_projects: int
    total_runtimes: int
    total_knowledge_sources: int
    total_api_keys: int
    total_webhooks: int
    total_requests_24h: int
    total_errors_24h: int
    avg_latency_ms_24h: float
    total_cost_cents_24h: int
    active_runtimes: int
    queued_runtimes: int
    failed_runtimes: int


class AdminUserRead(BaseModel):
    id: str
    email: str
    name: str | None
    organization_id: str | None
    is_active: bool
    created_at: str


class AdminProjectRead(BaseModel):
    id: str
    name: str
    slug: str
    organization_id: str
    status: str
    created_at: str


class AdminRuntimeRead(BaseModel):
    id: str
    project_id: str
    status: str
    provider: str
    model: str
    version: str
    health: float
    created_at: str


class AdminSystemInfo(BaseModel):
    app_name: str
    app_env: str
    app_version: str
    database_url: str
    redis_url: str
    celery_broker_url: str
    vector_provider: str
    rate_limit_per_minute: int
    enable_memory: bool
    enable_rag: bool
    enable_analytics: bool
    enable_tools: bool
    enable_router: bool
    uptime_seconds: float
    python_version: str
