from __future__ import annotations

import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing import UsageLog
from app.models.runtimes import Runtime
from app.models.users import User
from app.schemas.capabilities import (
    CrossSourceJoinRequest,
    EvaluationCase,
    EvaluationCaseResult,
)


ROLE_DEFAULTS: dict[str, dict[str, Any]] = {
    "owner": {"can_invoke": True, "can_read_sources": True, "can_use_tools": True, "can_write": True},
    "admin": {"can_invoke": True, "can_read_sources": True, "can_use_tools": True, "can_write": True},
    "developer": {"can_invoke": True, "can_read_sources": True, "can_use_tools": True, "can_write": False},
    "support": {"can_invoke": True, "can_read_sources": True, "can_use_tools": False, "can_write": False},
    "instructor": {"can_invoke": True, "can_read_sources": True, "can_use_tools": True, "can_write": False},
    "student": {"can_invoke": True, "can_read_sources": True, "can_use_tools": False, "can_write": False},
    "readonly": {"can_invoke": True, "can_read_sources": True, "can_use_tools": False, "can_write": False},
}


def default_access_policy() -> dict[str, Any]:
    return {
        "enabled": True,
        "default_role": "developer",
        "roles": {
            role: {**values, "allowed_sources": []}
            for role, values in ROLE_DEFAULTS.items()
        },
    }


def normalize_access_policy(raw: dict[str, Any] | None) -> dict[str, Any]:
    value = default_access_policy()
    if isinstance(raw, dict):
        value["enabled"] = bool(raw.get("enabled", value["enabled"]))
        value["default_role"] = str(raw.get("default_role") or value["default_role"]).strip().lower()
        configured_roles = raw.get("roles")
        if isinstance(configured_roles, dict):
            for role, settings in configured_roles.items():
                if not isinstance(settings, dict):
                    continue
                role_name = str(role).strip().lower()
                if not role_name:
                    continue
                defaults = ROLE_DEFAULTS.get(role_name, ROLE_DEFAULTS["readonly"])
                value["roles"][role_name] = {
                    "can_invoke": bool(settings.get("can_invoke", defaults["can_invoke"])),
                    "can_read_sources": bool(settings.get("can_read_sources", defaults["can_read_sources"])),
                    "can_use_tools": bool(settings.get("can_use_tools", defaults["can_use_tools"])),
                    "can_write": bool(settings.get("can_write", defaults["can_write"])),
                    "allowed_sources": sorted({str(item).strip().lower() for item in settings.get("allowed_sources", []) if str(item).strip()}),
                }
    if value["default_role"] not in value["roles"]:
        value["default_role"] = "developer"
    return value


def normalize_budget_policy(raw: dict[str, Any] | None) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    output: dict[str, Any] = {"enabled": bool(raw.get("enabled", False))}
    for key in ("max_request_usd", "monthly_limit_usd"):
        item = raw.get(key)
        if item is not None:
            try:
                output[key] = float(Decimal(str(item)))
            except Exception:
                output[key] = None
        else:
            output[key] = None
    rpm = raw.get("requests_per_minute")
    output["requests_per_minute"] = int(rpm) if isinstance(rpm, (int, float)) and rpm > 0 else None
    return output


def resolve_role(user: User, api_key_scopes: set[str] | None = None) -> str:
    if user.is_superuser:
        return "owner"
    settings = user.settings if isinstance(user.settings, dict) else {}
    role = settings.get("role") or settings.get("organization_role")
    resolved = str(role).strip().lower() if role else "developer"
    # API-key role hints may narrow a user's role, never elevate it.  This
    # keeps a leaked/over-scoped key from granting administrator access.
    role_scope = next((item[5:].strip().lower() for item in (api_key_scopes or set()) if item.startswith("role:") and item[5:].strip()), None)
    rank = {"readonly": 0, "student": 0, "support": 1, "developer": 2, "instructor": 2, "admin": 3, "owner": 4}
    if role_scope and rank.get(role_scope, -1) <= rank.get(resolved, 2):
        return role_scope
    return resolved


def authorize_runtime_request(
    runtime: Runtime,
    user: User,
    *,
    api_key_scopes: set[str] | None = None,
    requires_write: bool = False,
    sources: list[str] | None = None,
) -> tuple[str, dict[str, Any]]:
    raw = (runtime.config or {}).get("access_control") if isinstance(runtime.config, dict) else None
    policy = normalize_access_policy(raw)
    role = "owner" if runtime.user_id == user.id else resolve_role(user, api_key_scopes)
    if not raw or not policy["enabled"]:
        return role, policy
    role_policy = policy["roles"].get(role) or policy["roles"][policy["default_role"]]
    if not role_policy["can_invoke"]:
        raise PermissionError(f"Role '{role}' cannot invoke this runtime")
    if requires_write and not role_policy["can_write"]:
        raise PermissionError(f"Role '{role}' cannot perform write operations")
    if sources:
        if not role_policy["can_read_sources"]:
            raise PermissionError(f"Role '{role}' cannot read runtime sources")
        allowed = set(role_policy.get("allowed_sources") or [])
        if allowed and not set(item.lower() for item in sources).issubset(allowed):
            raise PermissionError("One or more requested sources are not allowed for this role")
    return role, policy


async def check_runtime_budget(
    db: AsyncSession,
    runtime: Runtime,
    *,
    estimated_cost: Decimal,
) -> tuple[bool, str | None, dict[str, Any]]:
    raw = (runtime.config or {}).get("budgets") if isinstance(runtime.config, dict) else None
    policy = normalize_budget_policy(raw)
    if not raw or not policy["enabled"]:
        return True, None, policy
    if policy["max_request_usd"] is not None and float(estimated_cost) > policy["max_request_usd"]:
        return False, "request_budget_exceeded", policy
    now = datetime.now(UTC)
    if policy["requests_per_minute"] is not None:
        minute_count = await db.scalar(
            select(func.coalesce(func.sum(UsageLog.requests), 0)).where(
                UsageLog.runtime_id == runtime.id,
                UsageLog.created_at >= now - timedelta(minutes=1),
            )
        )
        if int(minute_count or 0) >= policy["requests_per_minute"]:
            return False, "request_rate_limit_exceeded", policy
    if policy["monthly_limit_usd"] is not None:
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        monthly = await db.scalar(
            select(func.coalesce(func.sum(UsageLog.cost), 0)).where(
                UsageLog.runtime_id == runtime.id,
                UsageLog.created_at >= month_start,
            )
        )
        if Decimal(str(monthly or 0)) + estimated_cost > Decimal(str(policy["monthly_limit_usd"])):
            return False, "monthly_budget_exceeded", policy
    return True, None, policy


def join_source_records(request: CrossSourceJoinRequest) -> dict[str, Any]:
    """Join normalized records while retaining provenance for citations/debugging."""
    sets = request.sources
    sources = [item.source.strip().lower() for item in sets]
    if request.join_on:
        grouped: dict[Any, dict[str, Any]] = defaultdict(dict)
        for source_set in sets:
            source = source_set.source.strip().lower()
            for record in source_set.records:
                key = record.get(request.join_on)
                if key is None:
                    continue
                grouped[key][source] = record
        rows = []
        for key, by_source in grouped.items():
            if len(by_source) != len(sets):
                continue
            merged: dict[str, Any] = {request.join_on: key}
            for source, record in by_source.items():
                merged[source] = record
            rows.append(merged)
            if len(rows) >= request.limit:
                break
    else:
        rows = []
        for source_set in sets:
            source = source_set.source.strip().lower()
            for record in source_set.records:
                rows.append({"source": source, "record": record})
                if len(rows) >= request.limit:
                    break
            if len(rows) >= request.limit:
                break
    provenance = [
        {"source": source_set.source, "records": len(source_set.records), "join_key": request.join_on}
        for source_set in sets
    ]
    return {
        "sources": sources,
        "records": rows,
        "matched_records": len(rows),
        "join_on": request.join_on,
        "provenance": provenance,
    }


def evaluate_case(case: EvaluationCase, response: str | None) -> EvaluationCaseResult:
    text = response or ""
    lowered = text.casefold()
    contains_checks = {item: item.casefold() in lowered for item in case.expected_contains}
    citations_ok = (not case.expected_citations) or bool(re.search(r"https?://|\[[^\]]+\]\([^\)]+\)", text))
    checks: dict[str, bool] = {f"contains:{key}": value for key, value in contains_checks.items()}
    checks["citations"] = citations_ok
    passed_checks = sum(checks.values())
    score = passed_checks / len(checks) if checks else (1.0 if response else 0.0)
    return EvaluationCaseResult(
        case_id=case.id or case.name,
        passed=bool(response) and score >= 1.0,
        score=round(score, 4),
        checks=checks,
        response=response,
    )
