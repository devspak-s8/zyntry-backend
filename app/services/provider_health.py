"""Process-local provider health and failover state.

Provider capability metadata changes slowly, while availability changes every
few seconds.  Keeping these concerns separate lets the router avoid a provider
that is repeatedly failing without mutating the public model registry.  The
state is intentionally best-effort and process-local for V1; deployments with
multiple API workers can replace the store with Redis later.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from threading import Lock
from typing import Any

from app.core.redis import redis_client


@dataclass(slots=True)
class ProviderHealthState:
    provider: str
    consecutive_failures: int = 0
    total_failures: int = 0
    total_successes: int = 0
    last_latency_ms: float | None = None
    last_error: str | None = None
    last_checked_at: float | None = None
    unhealthy_until: float | None = None

    @property
    def available(self) -> bool:
        return not self.unhealthy_until or self.unhealthy_until <= time.monotonic()

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["available"] = self.available
        if self.last_checked_at is not None:
            data["last_checked_at"] = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.last_checked_at)
            )
        return data


class ProviderHealth:
    """Track short-lived failures used by model selection and failover."""

    def __init__(
        self,
        *,
        failure_threshold: int = 3,
        cooldown_seconds: int = 30,
        redis: Any | None = redis_client,
    ) -> None:
        self.failure_threshold = max(1, failure_threshold)
        self.cooldown_seconds = max(1, cooldown_seconds)
        self.redis = redis
        self._states: dict[str, ProviderHealthState] = {}
        self._lock = Lock()

    def _get(self, provider: str) -> ProviderHealthState:
        normalized = provider.strip().lower()
        state = self._states.get(normalized)
        if state is None:
            state = ProviderHealthState(provider=normalized)
            self._states[normalized] = state
        return state

    def is_available(self, provider: str) -> bool:
        with self._lock:
            return self._get(provider).available

    async def is_available_async(self, provider: str) -> bool:
        """Check local state and a short-lived distributed cooldown."""

        if not self.is_available(provider):
            return False
        if self.redis is None:
            return True
        try:
            blocked = await asyncio.wait_for(
                self.redis.get(self._redis_key(provider)),
                timeout=0.25,
            )
            return not bool(blocked)
        except Exception:
            # Provider health is advisory.  A Redis outage must not make every
            # model unavailable; runtime security retains its own fail-closed
            # policy for security-critical checks.
            return True

    def record_success(self, provider: str, latency_ms: float | None = None) -> None:
        with self._lock:
            state = self._get(provider)
            state.consecutive_failures = 0
            state.total_successes += 1
            state.last_latency_ms = latency_ms
            state.last_error = None
            state.last_checked_at = time.time()
            state.unhealthy_until = None

    async def record_success_async(self, provider: str, latency_ms: float | None = None) -> None:
        self.record_success(provider, latency_ms)
        if self.redis is not None:
            try:
                await asyncio.wait_for(
                    self.redis.delete(self._redis_key(provider)),
                    timeout=0.25,
                )
            except Exception:
                pass

    def record_failure(self, provider: str, error: str) -> None:
        with self._lock:
            state = self._get(provider)
            state.consecutive_failures += 1
            state.total_failures += 1
            state.last_error = str(error)[:500]
            state.last_checked_at = time.time()
            if state.consecutive_failures >= self.failure_threshold:
                state.unhealthy_until = time.monotonic() + self.cooldown_seconds

    async def record_failure_async(self, provider: str, error: str) -> None:
        self.record_failure(provider, error)
        state = self._get(provider)
        if state.unhealthy_until and self.redis is not None:
            try:
                await asyncio.wait_for(
                    self.redis.set(
                        self._redis_key(provider),
                        "1",
                        ex=self.cooldown_seconds,
                    ),
                    timeout=0.25,
                )
            except Exception:
                pass

    def snapshot(self, providers: Iterable[str] | None = None) -> list[dict[str, Any]]:
        with self._lock:
            names = {str(item).strip().lower() for item in providers or () if str(item).strip()}
            states = [
                state
                for name, state in self._states.items()
                if not names or name in names
            ]
            return [state.as_dict() for state in sorted(states, key=lambda item: item.provider)]

    def reset(self, provider: str | None = None) -> None:
        with self._lock:
            if provider is None:
                self._states.clear()
            else:
                self._states.pop(provider.strip().lower(), None)

    @staticmethod
    def _redis_key(provider: str) -> str:
        return f"zyntry:provider_health:{provider.strip().lower()}"


class FailoverManager:
    """Keep failover policy separate from the initial routing score."""

    def __init__(self, health: ProviderHealth | None = None) -> None:
        self.health = health or provider_health

    def eligible(self, candidates: Iterable[Any]) -> list[Any]:
        return [
            candidate
            for candidate in candidates
            if self.health.is_available(candidate.provider_name)
        ]

    async def eligible_async(self, candidates: Iterable[Any]) -> list[Any]:
        result = []
        availability: dict[str, bool] = {}
        for candidate in candidates:
            provider = str(candidate.provider_name).strip().lower()
            if provider not in availability:
                availability[provider] = await self.health.is_available_async(provider)
            if availability[provider]:
                result.append(candidate)
        return result

    def succeeded(self, candidate: Any, latency_ms: float | None = None) -> None:
        self.health.record_success(candidate.provider_name, latency_ms)

    async def succeeded_async(self, candidate: Any, latency_ms: float | None = None) -> None:
        await self.health.record_success_async(candidate.provider_name, latency_ms)

    def failed(self, candidate: Any, error: str) -> None:
        self.health.record_failure(candidate.provider_name, error)

    async def failed_async(self, candidate: Any, error: str) -> None:
        await self.health.record_failure_async(candidate.provider_name, error)


provider_health = ProviderHealth()
failover_manager = FailoverManager(provider_health)
