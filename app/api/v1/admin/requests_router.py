from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.constants import Permission
from app.admin.dependencies import AdminContext, require_permission
from app.admin.schemas import (
    RequestLogRead,
    RequestLogStatsRead,
)
from app.core.database import get_session
from app.models.billing import UsageLog
from app.models.request_logs import RequestLog

router = APIRouter(prefix="/admin", tags=["admin-requests"])


@router.get("/requests", response_model=list[RequestLogRead])
async def admin_list_requests(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    organization_id: str | None = Query(default=None),
    runtime_id: str | None = Query(default=None),
    user_id: str | None = Query(default=None),
    provider: str | None = Query(default=None),
    status_code: int | None = Query(default=None),
    ip_address: str | None = Query(default=None),
    country: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    endpoint: str | None = Query(default=None),
    ctx: AdminContext = Depends(require_permission(Permission.REQUESTS_READ)),
    db: AsyncSession = Depends(get_session),
) -> list[RequestLogRead]:
    stmt = (
        select(RequestLog, UsageLog)
        .outerjoin(UsageLog, UsageLog.request_id == RequestLog.request_id)
        .order_by(desc(RequestLog.created_at))
        .offset(offset)
        .limit(limit)
    )
    if organization_id:
        stmt = stmt.where(UsageLog.organization_id == _uuid_filter(organization_id, "organization_id"))
    if runtime_id:
        stmt = stmt.where(UsageLog.runtime_id == _uuid_filter(runtime_id, "runtime_id"))
    if user_id:
        stmt = stmt.where(RequestLog.user_id == _uuid_filter(user_id, "user_id"))
    if provider:
        stmt = stmt.where(RequestLog.provider == provider)
    if status_code is not None:
        stmt = stmt.where(RequestLog.status == status_code)
    if ip_address:
        stmt = stmt.where(RequestLog.ip == ip_address)
    if endpoint:
        stmt = stmt.where(RequestLog.endpoint.ilike(f"%{endpoint}%"))
    if date_from:
        stmt = stmt.where(RequestLog.created_at >= _parse_date(date_from, "date_from"))
    if date_to:
        stmt = stmt.where(RequestLog.created_at <= _parse_date(date_to, "date_to"))
    if country:
        # Country is populated by the admin event timeline, not RequestLog. An
        # explicit country filter must not silently return unrelated requests.
        stmt = stmt.where(UsageLog.metadata_["country"].as_string() == country)

    result = await db.execute(stmt)
    return [_to_read(log, usage) for log, usage in result.all()]


@router.get("/requests/stats", response_model=RequestLogStatsRead)
async def admin_request_stats(
    ctx: AdminContext = Depends(require_permission(Permission.REQUESTS_READ)),
    db: AsyncSession = Depends(get_session),
) -> RequestLogStatsRead:
    result = await db.execute(select(RequestLog.status, RequestLog.latency_ms, RequestLog.cost))
    rows = result.all()
    latencies = sorted(float(row.latency_ms or 0) for row in rows)
    costs = [float(row.cost or 0) for row in rows]
    total = len(rows)
    errors = sum(1 for row in rows if int(row.status or 0) >= 400)

    def percentile(value: float) -> float:
        if not latencies:
            return 0.0
        index = min(len(latencies) - 1, max(0, int(round((len(latencies) - 1) * value))))
        return latencies[index]

    return RequestLogStatsRead(
        total_requests=total,
        avg_latency_ms=sum(latencies) / total if total else 0.0,
        avg_cost=sum(costs) / total if total else 0.0,
        error_rate=errors / total if total else 0.0,
        p95_latency_ms=percentile(0.95),
        p99_latency_ms=percentile(0.99),
    )


def _uuid_filter(value: str, name: str):
    import uuid

    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {name}") from exc


def _parse_date(value: str, name: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {name}") from exc


def _to_read(log: RequestLog, usage: UsageLog | None) -> RequestLogRead:
    return RequestLogRead(
        id=str(log.id),
        organization_id=str(usage.organization_id) if usage and usage.organization_id else None,
        user_id=str(log.user_id) if log.user_id else (str(usage.user_id) if usage else None),
        api_key_id=str(usage.api_key_id) if usage and usage.api_key_id else None,
        runtime_id=str(usage.runtime_id) if usage and usage.runtime_id else None,
        endpoint=log.endpoint,
        method=log.method,
        ip_address=log.ip,
        country=(usage.metadata_ or {}).get("country") if usage else None,
        asn=(usage.metadata_ or {}).get("asn") if usage else None,
        user_agent=(usage.metadata_ or {}).get("user_agent") if usage else None,
        fingerprint_hash=(usage.metadata_ or {}).get("fingerprint_hash") if usage else None,
        provider=log.provider,
        model=log.model,
        input_tokens=usage.input_tokens if usage else None,
        output_tokens=usage.output_tokens if usage else None,
        total_tokens=(usage.input_tokens + usage.output_tokens) if usage else log.tokens,
        cost=float(usage.cost) if usage else (float(log.cost) if log.cost is not None else None),
        latency_ms=log.latency_ms,
        status_code=log.status,
        knowledge_chunks=(usage.vector_searches if usage else None),
        tools_executed=(usage.metadata_ or {}).get("tools_executed") if usage else None,
        created_at=log.created_at.isoformat() if log.created_at else "",
    )
