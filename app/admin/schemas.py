from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.admin.constants import FeatureFlagType, FeatureScope


def _validate_feature_allowlist(values: list[str] | None) -> list[str] | None:
    if values is None:
        return None

    normalized: list[str] = []
    for raw_value in values:
        prefix, separator, identifier = raw_value.strip().partition(":")
        prefix = prefix.lower()
        identifier = identifier.strip()
        if not separator or prefix not in {"user", "org", "email"} or not identifier:
            raise ValueError(
                "allowlist entries must use user:<uuid>, org:<uuid>, or email:<address>"
            )
        if prefix in {"user", "org"}:
            try:
                identifier = str(uuid.UUID(identifier))
            except ValueError as exc:
                raise ValueError(f"{prefix} allowlist entries must contain a valid UUID") from exc
        else:
            identifier = identifier.lower()
            if "@" not in identifier:
                raise ValueError("email allowlist entries must contain a valid email address")
        entry = f"{prefix}:{identifier}"
        if entry not in normalized:
            normalized.append(entry)
    return normalized


class AdminUserRead(BaseModel):
    id: str
    email: str
    name: str | None = None
    role: str
    is_active: bool
    mfa_enabled: bool
    created_at: str


class AdminUserCreate(BaseModel):
    user_id: str
    role: str = "viewer"


class AdminUserUpdate(BaseModel):
    role: str | None = None
    mfa_enabled: bool | None = None
    is_active: bool | None = None


class AdminSessionRead(BaseModel):
    id: str
    user_id: str
    admin_user_id: str
    ip_address: str | None = None
    user_agent: str | None = None
    expires_at: str
    revoked: bool
    mfa_verified: bool


class AdminAuditLogRead(BaseModel):
    id: str
    admin_user_id: str | None
    user_id: str | None
    action: str
    resource_type: str
    resource_id: str | None
    previous_value: dict[str, Any] | None = None
    new_value: dict[str, Any] | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    reason: str | None = None
    success: bool
    created_at: str


class IPAllowListRead(BaseModel):
    id: str
    ip_address: str
    description: str | None = None
    is_active: bool


class IPAllowListCreate(BaseModel):
    ip_address: str
    description: str | None = None


class IPRecordRead(BaseModel):
    id: str
    ip_address: str
    country: str | None = None
    city: str | None = None
    region: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    asn: int | None = None
    isp: str | None = None
    is_vpn: bool
    is_proxy: bool
    is_tor: bool
    total_requests: int
    failed_requests: int
    accounts_created: int
    api_keys_generated: int
    risk_score: int
    is_banned: bool
    ban_type: str | None = None
    ban_reason: str | None = None
    ban_expires_at: str | None = None
    first_seen: str
    last_seen: str


class UserFingerprintRead(BaseModel):
    id: str
    user_id: str | None = None
    organization_id: str | None = None
    fingerprint_hash: str
    browser: str | None = None
    os_name: str | None = None
    device: str | None = None
    timezone: str | None = None
    language: str | None = None
    screen_resolution: str | None = None
    is_trusted: bool
    risk_score: int
    first_seen: str
    last_seen: str


class LoginEventRead(BaseModel):
    id: str
    user_id: str | None = None
    organization_id: str | None = None
    ip_address: str
    country: str | None = None
    success: bool
    failure_reason: str | None = None
    created_at: str


class SecurityAlertRead(BaseModel):
    id: str
    alert_type: str
    risk_score: int
    risk_level: str
    status: str
    title: str
    description: str | None = None
    ip_address: str | None = None
    country: str | None = None
    asn: int | None = None
    user_id: str | None = None
    organization_id: str | None = None
    first_seen: str
    last_seen: str
    attempt_count: int
    triggered_rules: list[str] | None = None
    acknowledged_by: str | None = None
    resolved_at: str | None = None


class SecurityAlertAction(BaseModel):
    action: str
    reason: str | None = None


class FeatureFlagRead(BaseModel):
    id: str
    key: str
    name: str
    description: str | None = None
    scope: str
    flag_type: str
    enabled: bool
    default_value: bool | None = None
    rollout_percentage: int
    allowlist: list[str] | None = None
    is_system: bool
    updated_by: str | None = None


class FeatureFlagCreate(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,99}$")
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    scope: FeatureScope = FeatureScope.PROVIDER
    flag_type: FeatureFlagType = FeatureFlagType.TOGGLE
    enabled: bool = False
    default_value: bool | None = None
    rollout_percentage: int = Field(default=100, ge=0, le=100)
    allowlist: list[str] | None = None

    _normalize_allowlist = field_validator("allowlist")(_validate_feature_allowlist)


class FeatureFlagUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    enabled: bool | None = None
    default_value: bool | None = None
    rollout_percentage: int | None = Field(default=None, ge=0, le=100)
    allowlist: list[str] | None = None

    _normalize_allowlist = field_validator("allowlist")(_validate_feature_allowlist)


class NotificationConfigRead(BaseModel):
    id: str
    event_type: str
    provider_type: str
    name: str
    is_enabled: bool
    config: dict[str, Any] | None = None


class NotificationConfigCreate(BaseModel):
    event_type: str
    provider_type: str
    name: str
    is_enabled: bool = True
    config: dict[str, Any] | None = None


class NotificationEventRead(BaseModel):
    id: str
    event_type: str
    title: str
    description: str | None = None
    is_read: bool
    created_at: str


class DashboardMetricsRead(BaseModel):
    total_users: int
    total_organizations: int
    total_projects: int
    total_runtimes: int
    total_wallet_balance: float
    total_requests_24h: int
    total_cost_24h: float
    avg_latency_ms_24h: float
    active_runtimes: int
    queued_runtimes: int
    failed_runtimes: int


class DashboardLiveMetricsRead(BaseModel):
    requests_per_second: float
    active_connections: int
    avg_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    error_rate: float
    queue_size: int
    redis_memory_mb: float
    pg_connections: int
    cpu_percent: float
    memory_percent: float
    disk_percent: float
    network_throughput_mb: float
    revenue_today: float
    revenue_month: float
    wallet_balance: float
    provider_cost: float
    profit_margin: float
    uptime_seconds: float


class RuntimeDetailRead(BaseModel):
    id: str
    project_id: str
    organization_id: str
    name: str
    status: str
    provider: str
    model: str
    embedding_model: str | None = None
    vector_store: str | None = None
    config: dict[str, Any] | None = None
    documents: int
    chunks: int
    embeddings: int
    index_size: int
    health: str
    error_message: str | None = None
    created_at: str
    updated_at: str
    disabled: bool
    disabled_by_admin: bool | None = None
    avg_latency_ms: float | None = None
    avg_cost: float | None = None
    invocation_count: int | None = None
    error_count: int | None = None
    cache_hit_rate: float | None = None
    queue_time_ms: float | None = None
    connected_sources: int
    connected_tools: int
    last_invocation: str | None = None


class RuntimeAction(BaseModel):
    action: str


class RequestLogRead(BaseModel):
    id: str
    organization_id: str | None = None
    user_id: str | None = None
    api_key_id: str | None = None
    runtime_id: str | None = None
    endpoint: str
    method: str
    ip_address: str | None = None
    country: str | None = None
    asn: int | None = None
    user_agent: str | None = None
    fingerprint_hash: str | None = None
    provider: str | None = None
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cost: Decimal | None = None
    latency_ms: int | None = None
    status_code: int | None = None
    knowledge_chunks: int | None = None
    tools_executed: int | None = None
    created_at: str


class RequestLogFilter(BaseModel):
    organization_id: str | None = None
    runtime_id: str | None = None
    user_id: str | None = None
    provider: str | None = None
    status_code: int | None = None
    ip_address: str | None = None
    country: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    endpoint: str | None = None


class RequestLogStatsRead(BaseModel):
    total_requests: int
    avg_latency_ms: float
    avg_cost: float
    error_rate: float
    p95_latency_ms: float
    p99_latency_ms: float


class SecurityAlertSummaryRead(BaseModel):
    total_alerts: int
    open_alerts: int
    critical_alerts: int
    high_alerts: int
    medium_alerts: int
    low_alerts: int


class AlertActionRequest(BaseModel):
    action: str
    reason: str | None = None


class AlertTimelineEvent(BaseModel):
    id: str
    alert_id: str
    action: str
    performed_by: str | None = None
    reason: str | None = None
    created_at: str


class IPStatsRead(BaseModel):
    ip_address: str
    country: str | None = None
    city: str | None = None
    asn: int | None = None
    isp: str | None = None
    is_vpn: bool
    is_proxy: bool
    is_tor: bool
    total_requests: int
    failed_requests: int
    accounts_created: int
    api_keys_generated: int
    risk_score: int
    is_banned: bool
    ban_type: str | None = None
    ban_reason: str | None = None
    first_seen: str
    last_seen: str


class IPBanRequest(BaseModel):
    ban_type: str = "temporary"
    reason: str | None = None
    duration_hours: int | None = None


class IPActionRequest(BaseModel):
    action: str
    reason: str | None = None
    duration_hours: int | None = None


class FingerprintDetailRead(BaseModel):
    id: str
    user_id: str | None = None
    organization_id: str | None = None
    fingerprint_hash: str
    browser: str | None = None
    os_name: str | None = None
    device: str | None = None
    timezone: str | None = None
    language: str | None = None
    screen_resolution: str | None = None
    canvas_fingerprint: str | None = None
    webgl_fingerprint: str | None = None
    tls_signature: str | None = None
    is_trusted: bool
    risk_score: int
    first_seen: str
    last_seen: str
    metadata_: dict[str, Any] | None = None


class FingerprintTrustUpdate(BaseModel):
    is_trusted: bool


class FingerprintFlagRequest(BaseModel):
    risk_score: int


class RuntimeUsageRead(BaseModel):
    runtime_id: str
    invocation_count: int
    avg_latency_ms: float
    avg_cost: float
    error_count: int
    cache_hit_rate: float
    queue_time_ms: float


class ModelAnalyticsRead(BaseModel):
    provider: str
    model: str
    requests: int
    avg_latency_ms: float
    avg_cost: float
    failures: int
    avg_tokens: int
    success_rate: float
    is_recommended: bool
    recommendation_reason: str | None = None


class ProviderPerformanceRead(BaseModel):
    provider: str
    total_requests: int
    avg_latency_ms: float
    avg_cost: float
    total_failures: int
    success_rate: float
    is_recommended: bool
    recommendation_reason: str | None = None


class BillingOverviewRead(BaseModel):
    wallet_balance: float
    credits_purchased: float
    credits_used: float
    provider_cost: float
    platform_revenue: float
    profit_margin: float
    refunds: float
    pending_payments: float
    failed_payments: float


class WalletDetailRead(BaseModel):
    id: str
    user_id: str
    user_name: str | None = None
    org_name: str | None = None
    balance: float
    currency: str
    status: str
    created_at: str
    updated_at: str


class WalletTransactionRead(BaseModel):
    id: str
    wallet_id: str
    user_id: str
    user_name: str | None = None
    org_name: str | None = None
    type: str
    amount: float
    balance_after: float
    reason: str | None = None
    created_at: str


class WalletCreditRequest(BaseModel):
    amount: float
    reason: str | None = None


class WalletDebitRequest(BaseModel):
    amount: float
    reason: str | None = None


class WalletAdjustRequest(BaseModel):
    new_balance: float
    reason: str | None = None


class WalletRefundRequest(BaseModel):
    transaction_id: str
    reason: str | None = None


class WalletFreezeRequest(BaseModel):
    reason: str | None = None


class UsageOverviewRead(BaseModel):
    total_requests: int
    total_cost: float
    total_tokens: int
    avg_tokens_per_request: float
    avg_cost_per_request: float
    top_organizations: list[dict[str, Any]]
    top_users: list[dict[str, Any]]
    top_api_keys: list[dict[str, Any]]
    top_models: list[dict[str, Any]]
    top_providers: list[dict[str, Any]]
    top_runtimes: list[dict[str, Any]]
    top_knowledge_sources: list[dict[str, Any]]
    top_tools: list[dict[str, Any]]
    top_endpoints: list[dict[str, Any]]


class EventTimelineRead(BaseModel):
    id: str
    request_id: str
    event_type: str
    title: str
    description: str | None = None
    sequence: int
    timestamp: str
    organization_id: str | None = None
    user_id: str | None = None
    runtime_id: str | None = None
    provider: str | None = None
    model: str | None = None
    latency_ms: int | None = None
    status_code: int | None = None
    cost: Decimal | None = None
    data: dict[str, Any] | None = None


class EventReplayRead(BaseModel):
    request_id: str
    timeline: list[EventTimelineRead]
    runtime_id: str | None = None
    user_id: str | None = None
    org_id: str | None = None
    usage: dict[str, Any] | None = None
    runtime_data: dict[str, Any] | None = None


class HealthCheckRead(BaseModel):
    service: str
    status: str
    duration_ms: float
    details: dict[str, Any] | None = None


class HealthSystemRead(BaseModel):
    fastapi: HealthCheckRead
    redis: HealthCheckRead
    postgresql: HealthCheckRead
    workers: HealthCheckRead
    scheduler: HealthCheckRead
    system_resources: HealthCheckRead
    storage: HealthCheckRead
    external_apis: HealthCheckRead
    model_providers: HealthCheckRead
    queue_health: HealthCheckRead
    overall: str


class ProviderHealthRead(BaseModel):
    provider: str
    status: str
    avg_latency_ms: float | None = None
    error_rate: float | None = None


class SystemHealthRead(BaseModel):
    overall: str
    checks: dict[str, HealthCheckRead]
    providers: list[ProviderHealthRead]


class AuditLogEntryRead(BaseModel):
    id: str
    admin_user_id: str | None = None
    user_id: str | None = None
    action: str
    resource_type: str
    resource_id: str | None = None
    previous_value: dict[str, Any] | None = None
    new_value: dict[str, Any] | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    reason: str | None = None
    success: bool
    created_at: str


class AuditLogSummaryRead(BaseModel):
    total_entries: int
    actions: dict[str, int]
    top_admins: list[dict[str, Any]]


class AnalyticsOverviewRead(BaseModel):
    total_requests: int
    total_cost: float
    total_tokens: int
    avg_tokens_per_request: float
    avg_cost_per_request: float
    top_organizations: list[dict[str, Any]]
    top_users: list[dict[str, Any]]
    top_api_keys: list[dict[str, Any]]
    top_models: list[dict[str, Any]]
    top_providers: list[dict[str, Any]]
    top_runtimes: list[dict[str, Any]]
    top_knowledge_sources: list[dict[str, Any]]
    top_tools: list[dict[str, Any]]
    top_endpoints: list[dict[str, Any]]


class AnalyticsSummaryRead(BaseModel):
    period: str
    total_requests: int
    total_cost: float
    total_tokens: int
    avg_latency_ms: float
    avg_cost_per_request: float
    error_rate: float
    top_models: list[dict[str, Any]]
    top_providers: list[dict[str, Any]]
    top_endpoints: list[dict[str, Any]]
