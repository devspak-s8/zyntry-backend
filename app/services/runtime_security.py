"""Small, runtime-scoped request security controls for the V1 invoke path."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Request

from app.core.redis import redis_client
from app.services.actions.guardrails import GuardrailService as ActionGuardrailService


DEFAULT_RUNTIME_SECURITY_POLICY: dict[str, Any] = {
    "enabled": False,
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
}


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
    return merged


class RuntimeSecurityService:
    def __init__(self, redis: Any = redis_client) -> None:
        self.redis = redis

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
        if await self._is_blocked(runtime_id, client_ip):
            raise RuntimeSecurityViolation(
                status_code=403,
                code="ip_blocked",
                message="This client is temporarily blocked by the runtime security policy.",
            )

        await self._enforce_rate_limit(
            runtime_id,
            client_ip,
            policy["rate_limit_per_minute"],
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

    async def _is_blocked(self, runtime_id: str, client_ip: str) -> bool:
        try:
            return bool(await self.redis.get(self._block_key(runtime_id, client_ip)))
        except Exception:
            # Security controls should not turn a transient Redis outage into
            # an outage for otherwise valid runtime requests.
            return False

    async def _enforce_rate_limit(self, runtime_id: str, client_ip: str, limit: int) -> None:
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
            return

    @staticmethod
    def _block_key(runtime_id: str, client_ip: str) -> str:
        return f"runtime:security:block:{runtime_id}:{client_ip}"
