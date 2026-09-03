"""Small, runtime-scoped request security controls for the V1 invoke path."""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import re
from typing import Any

from fastapi import Request

from app.core.redis import redis_client
from app.services.actions.guardrails import GuardrailService as ActionGuardrailService


DEFAULT_RUNTIME_SECURITY_POLICY: dict[str, Any] = {
    # Safe request protection is on for newly created and legacy runtimes.
    # Owners can still disable it explicitly from Runtime Settings.
    "enabled": True,
    "block_suspicious_requests": True,
    # Keep the descriptive setting used by the console in sync with the
    # gateway switch.  Older runtime records may only have one of these keys.
    "prompt_injection_protection": True,
    "pii_redaction": True,
    "max_input_chars": 10000,
    "rate_limit_per_minute": 120,
    "ip_ban_enabled": True,
    "violation_threshold": 3,
    "ban_duration_seconds": 900,
    "allowed_ips": [],
    "blocked_ips": [],
    "redis_failure_mode": "fail_closed",
}

_EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PHONE_PATTERN = re.compile(
    r"(?<!\w)(?:\+\d{1,3}[\s.-])?(?:\(?\d{2,4}\)?[\s.-])\d{3,4}[\s.-]\d{3,4}(?!\w)"
)
_SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CARD_PATTERN = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")


def redact_pii(value: Any) -> Any:
    """Redact common PII from live runtime output without changing its shape."""
    if isinstance(value, dict):
        return {key: redact_pii(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_pii(item) for item in value]
    if isinstance(value, tuple):
        return [redact_pii(item) for item in value]
    if not isinstance(value, str):
        return value

    redacted = _EMAIL_PATTERN.sub("[REDACTED_EMAIL]", value)
    redacted = _PHONE_PATTERN.sub("[REDACTED_PHONE]", redacted)
    redacted = _SSN_PATTERN.sub("[REDACTED_SSN]", redacted)

    def replace_card(match: re.Match[str]) -> str:
        candidate = re.sub(r"[ -]", "", match.group(0))
        if len(candidate) < 13 or len(candidate) > 19:
            return match.group(0)
        digits = [int(char) for char in candidate]
        checksum = 0
        for index, digit in enumerate(reversed(digits)):
            if index % 2:
                digit *= 2
                if digit > 9:
                    digit -= 9
            checksum += digit
        return "[REDACTED_CARD]" if checksum % 10 == 0 else match.group(0)

    return _CARD_PATTERN.sub(replace_card, redacted)


def _normalize_ip_rules(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple, set)):
        raise ValueError("IP allow/block lists must be arrays")
    normalized: list[str] = []
    for raw in value:
        item = str(raw).strip()
        if not item:
            continue
        try:
            parsed = ipaddress.ip_network(item, strict=False) if "/" in item else ipaddress.ip_address(item)
        except ValueError as exc:
            raise ValueError(f"Invalid IP address or CIDR rule: {item}") from exc
        canonical = str(parsed)
        if canonical not in normalized:
            normalized.append(canonical)
    return normalized


def _ip_matches_rules(client_ip: str, rules: list[str]) -> bool:
    try:
        address = ipaddress.ip_address(client_ip)
    except ValueError:
        return False
    for rule in rules:
        try:
            network = ipaddress.ip_network(rule, strict=False)
        except ValueError:
            continue
        if address in network:
            return True
    return False


@dataclass
class RuntimeSecurityViolation(Exception):
    status_code: int
    code: str
    message: str

    def __str__(self) -> str:
        return self.message


def normalize_runtime_security_policy(policy: dict[str, Any] | None) -> dict[str, Any]:
    """Merge safe defaults while preserving unrelated policy metadata."""
    value = dict(policy or {})
    merged = {**DEFAULT_RUNTIME_SECURITY_POLICY, **value}
    integer_limits = {
        "max_input_chars": (1000, 1_000_000),
        "rate_limit_per_minute": (1, 100_000),
        "violation_threshold": (1, 100),
        "ban_duration_seconds": (60, 86_400),
    }
    for key, (minimum, maximum) in integer_limits.items():
        try:
            merged[key] = max(minimum, min(maximum, int(merged[key])))
        except (TypeError, ValueError):
            merged[key] = DEFAULT_RUNTIME_SECURITY_POLICY[key]
    merged["enabled"] = bool(merged["enabled"])
    merged["block_suspicious_requests"] = bool(merged["block_suspicious_requests"])
    merged["prompt_injection_protection"] = bool(merged["prompt_injection_protection"])
    merged["pii_redaction"] = bool(merged["pii_redaction"])
    # ``prompt_injection_protection`` is the user-facing name in the console;
    # it must be authoritative when supplied instead of silently leaving the
    # gateway's legacy flag enabled.
    if "prompt_injection_protection" in value:
        merged["block_suspicious_requests"] = merged["prompt_injection_protection"]
    merged["ip_ban_enabled"] = bool(merged["ip_ban_enabled"])
    merged["allowed_ips"] = _normalize_ip_rules(merged.get("allowed_ips"))
    merged["blocked_ips"] = _normalize_ip_rules(merged.get("blocked_ips"))
    failure_mode = str(merged.get("redis_failure_mode") or "fail_closed").strip().lower()
    if failure_mode not in {"fail_closed", "fail_open"}:
        failure_mode = "fail_closed"
    merged["redis_failure_mode"] = failure_mode
    return merged


async def persist_runtime_security_event(
    db: Any,
    runtime: Any,
    event_type: str,
    *,
    request_id: str | None = None,
    client_ip: str | None = None,
    code: str | None = None,
    message: str | None = None,
    status_code: int | None = None,
    pii_redacted: bool | None = None,
) -> None:
    """Persist a redacted security event for the customer-facing history API."""
    from app.models.events import Event

    data: dict[str, Any] = {
        "runtime_id": str(runtime.id),
        "request_id": request_id,
        "ip_address": client_ip,
        "code": code,
        "message": message,
        "status_code": status_code,
    }
    if pii_redacted is not None:
        data["pii_redacted"] = pii_redacted
    db.add(
        Event(
            project_id=getattr(runtime, "project_id", None),
            organization_id=getattr(runtime, "organization_id", None),
            event_type=f"runtime.security.{event_type}",
            data={key: value for key, value in data.items() if value is not None},
        )
    )
    await db.flush()


class RuntimeSecurityService:
    def __init__(self, redis: Any = redis_client) -> None:
        self.redis = redis

    async def clear_ip_block(self, runtime_id: str, client_ip: str) -> None:
        """Clear temporary abuse counters when an owner unblocks an IP."""
        try:
            delete = getattr(self.redis, "delete", None)
            if delete is None:
                return
            await delete(
                self._block_key(runtime_id, client_ip),
                f"runtime:security:violations:{runtime_id}:{client_ip}",
            )
        except Exception:
            # The durable policy update still removes a manual block. A
            # transient Redis outage should not turn the management request
            # into a 500.
            return

    async def enforce(
        self,
        runtime: Any,
        request: Request,
        prompt: str,
    ) -> dict[str, Any]:
        policy = normalize_runtime_security_policy(getattr(runtime, "security_policies", None))
        if not policy["enabled"]:
            return {"enabled": False, "checked": False}

        client_ip = request.client.host if request.client else "unknown"
        runtime_id = str(runtime.id)
        if _ip_matches_rules(client_ip, policy["blocked_ips"]):
            raise RuntimeSecurityViolation(
                status_code=403,
                code="ip_blocked",
                message="This client IP is blocked by the runtime security policy.",
            )
        if policy["allowed_ips"] and not _ip_matches_rules(client_ip, policy["allowed_ips"]):
            raise RuntimeSecurityViolation(
                status_code=403,
                code="ip_not_allowlisted",
                message="This client IP is not on the runtime allowlist.",
            )
        if await self._is_blocked(runtime_id, client_ip, policy):
            raise RuntimeSecurityViolation(
                status_code=403,
                code="ip_blocked",
                message="This client is temporarily blocked by the runtime security policy.",
            )

        await self._enforce_rate_limit(
            runtime_id,
            client_ip,
            policy["rate_limit_per_minute"],
            policy,
        )

        if len(prompt) > policy["max_input_chars"]:
            await self._record_violation(runtime_id, client_ip, policy)
            raise RuntimeSecurityViolation(
                status_code=413,
                code="input_too_large",
                message=(
                    f"Input exceeds this runtime's security limit of "
                    f"{policy['max_input_chars']} characters."
                ),
            )

        valid_prompt, reason = ActionGuardrailService.validate_prompt(prompt)
        if not valid_prompt and policy["block_suspicious_requests"]:
            await self._record_violation(runtime_id, client_ip, policy)
            raise RuntimeSecurityViolation(
                status_code=403,
                code="suspicious_request",
                message=reason or "Potentially unsafe prompt detected.",
            )
        return {
            "enabled": True,
            "checked": True,
            "client_ip": client_ip,
            "suspicious": not valid_prompt,
        }

    async def _is_blocked(self, runtime_id: str, client_ip: str, policy: dict[str, Any]) -> bool:
        try:
            return bool(await self.redis.get(self._block_key(runtime_id, client_ip)))
        except Exception:
            if policy["redis_failure_mode"] == "fail_closed":
                raise RuntimeSecurityViolation(
                    status_code=503,
                    code="security_unavailable",
                    message="Runtime security controls are temporarily unavailable. Please retry shortly.",
                )
            return False

    async def _enforce_rate_limit(
        self,
        runtime_id: str,
        client_ip: str,
        limit: int,
        policy: dict[str, Any],
    ) -> None:
        key = f"runtime:security:rate:{runtime_id}:{client_ip}"
        try:
            count = await self.redis.incr(key)
            if count == 1:
                await self.redis.expire(key, 60)
            if count > limit:
                raise RuntimeSecurityViolation(
                    status_code=429,
                    code="runtime_rate_limited",
                    message="This runtime has reached its request rate limit. Try again shortly.",
                )
        except RuntimeSecurityViolation:
            raise
        except Exception:
            if policy["redis_failure_mode"] == "fail_closed":
                raise RuntimeSecurityViolation(
                    status_code=503,
                    code="security_unavailable",
                    message="Runtime security controls are temporarily unavailable. Please retry shortly.",
                )
            return

    async def _record_violation(
        self,
        runtime_id: str,
        client_ip: str,
        policy: dict[str, Any],
    ) -> None:
        if not policy["ip_ban_enabled"]:
            return
        key = f"runtime:security:violations:{runtime_id}:{client_ip}"
        try:
            count = await self.redis.incr(key)
            if count == 1:
                await self.redis.expire(key, policy["ban_duration_seconds"])
            if count >= policy["violation_threshold"]:
                await self.redis.set(
                    self._block_key(runtime_id, client_ip),
                    "1",
                    ex=policy["ban_duration_seconds"],
                )
        except Exception:
            if policy["redis_failure_mode"] == "fail_closed":
                raise RuntimeSecurityViolation(
                    status_code=503,
                    code="security_unavailable",
                    message="Runtime security controls are temporarily unavailable. Please retry shortly.",
                )
            return

    @staticmethod
    def _block_key(runtime_id: str, client_ip: str) -> str:
        return f"runtime:security:block:{runtime_id}:{client_ip}"
