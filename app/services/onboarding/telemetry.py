"""Privacy-safe tracing for onboarding model calls.

The trace is deliberately request-scoped. Providers can report attempts through
the current sink without receiving prompts or credentials, and the sink only
persists counts, timings, identifiers, and safe error categories.
"""

from __future__ import annotations

import contextvars
import logging
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.onboarding_trace import OnboardingTraceEvent
from app.services.token_engine import TokenEngine

_CURRENT_TRACE: contextvars.ContextVar[OnboardingTraceSink | None] = contextvars.ContextVar(
    "onboarding_trace", default=None
)
_CURRENT_CALL: contextvars.ContextVar[uuid.UUID | None] = contextvars.ContextVar(
    "onboarding_trace_call", default=None
)

logger = logging.getLogger(__name__)


def classify_error(error: BaseException) -> tuple[str, int | None]:
    """Return a safe, stable error category and optional HTTP status."""

    response = getattr(error, "response", None)
    status = getattr(response, "status_code", None)
    if isinstance(status, int):
        if status == 429:
            return "rate_limit", status
        if status in {401, 403}:
            return "authentication", status
        if status == 408:
            return "timeout", status
        if status >= 500:
            return "provider_5xx", status
        if status >= 400:
            return "provider_4xx", status
    if isinstance(error, (TimeoutError, httpx.TimeoutException)):
        return "timeout", status if isinstance(status, int) else None
    if isinstance(error, httpx.RequestError):
        return "network", status if isinstance(status, int) else None
    if isinstance(error, (ValueError, TypeError, KeyError)):
        return "invalid_response", status if isinstance(status, int) else None
    if isinstance(error, RuntimeError) and "not configured" in str(error).lower():
        return "not_configured", status if isinstance(status, int) else None
    return "provider_error", status if isinstance(status, int) else None


@dataclass
class _ActiveCall:
    event: OnboardingTraceEvent
    started: float


@dataclass
class OnboardingTraceSink:
    session: AsyncSession
    user_id: uuid.UUID
    session_id: uuid.UUID | None
    turn_id: uuid.UUID = field(default_factory=uuid.uuid4)
    _active: dict[uuid.UUID, _ActiveCall] = field(default_factory=dict)

    def bind_session_id(self, session_id: uuid.UUID) -> None:
        self.session_id = session_id
        for active in self._active.values():
            active.event.session_id = session_id
        for item in self.session.new:
            if isinstance(item, OnboardingTraceEvent):
                item.session_id = session_id

    def start_call(
        self,
        *,
        operation: str,
        model: str | None,
        messages: list[dict[str, Any]],
    ) -> uuid.UUID:
        call_id = uuid.uuid4()
        context_tokens = TokenEngine.estimate_messages(messages)
        event = OnboardingTraceEvent(
            id=call_id,
            session_id=self.session_id,
            user_id=self.user_id,
            turn_id=self.turn_id,
            event_type="logical_call",
            operation=operation,
            provider=None,
            model=model,
            status="running",
            context_tokens=context_tokens,
            metadata_={
                "message_count": len(messages),
                "context_bytes": sum(len(str(item.get("content", ""))) for item in messages),
            },
        )
        self.session.add(event)
        self._active[call_id] = _ActiveCall(event=event, started=time.perf_counter())
        return call_id

    def finish_call(
        self,
        call_id: uuid.UUID,
        *,
        status: str,
        provider: str | None = None,
        model: str | None = None,
        usage: Any = None,
        output_text: str = "",
        error: BaseException | None = None,
        attempts: int = 1,
        fallback_used: bool = False,
        http_status: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        active = self._active.pop(call_id, None)
        if active is None:
            return
        event = active.event
        estimated_input = event.context_tokens
        estimated_output = TokenEngine.estimate_text(output_text)
        _, normalized = TokenEngine.normalize_usage(
            (output_text, usage),
            estimated_input_tokens=estimated_input,
            estimated_output_tokens=estimated_output,
        )
        event.provider = provider
        event.model = model or event.model
        event.status = status
        event.latency_ms = max(0, round((time.perf_counter() - active.started) * 1000))
        event.input_tokens = normalized.input_tokens
        event.output_tokens = normalized.output_tokens
        event.total_tokens = normalized.total_tokens
        event.usage_source = normalized.source
        event.retry_count = max(0, attempts - 1)
        event.fallback_used = fallback_used
        if error is not None:
            event.error_category, event.error_status = classify_error(error)
        event.metadata_ = {
            **(event.metadata_ or {}),
            **(metadata or {}),
            "attempts": max(1, attempts),
            "http_status": http_status if http_status is not None else event.error_status,
            "parse_success": status in {"completed", "repaired", "fallback"},
        }
        logger.info(
            "onboarding_model_call provider=%s model=%s call_type=%s duration_ms=%s "
            "http_status=%s parse_success=%s retry_count=%s finish_reason=%s "
            "response_schema_applied=%s schema_has_refs=%s",
            event.provider or "unknown",
            event.model or "unknown",
            event.operation,
            event.latency_ms,
            http_status if http_status is not None else event.error_status or "unknown",
            status in {"completed", "repaired", "fallback"},
            event.retry_count,
            (metadata or {}).get("finish_reason", "unknown"),
            (metadata or {}).get("response_schema_applied", "unknown"),
            (metadata or {}).get("schema_has_refs", "unknown"),
        )

    def start_attempt(
        self,
        *,
        operation: str,
        provider: str,
        model: str,
        attempt_number: int,
        status: str = "running",
    ) -> uuid.UUID:
        attempt_id = uuid.uuid4()
        event = OnboardingTraceEvent(
            id=attempt_id,
            session_id=self.session_id,
            user_id=self.user_id,
            turn_id=self.turn_id,
            parent_call_id=current_call_id(),
            event_type="provider_attempt",
            operation=operation,
            attempt_number=attempt_number,
            provider=provider,
            model=model,
            status=status,
        )
        self.session.add(event)
        self._active[attempt_id] = _ActiveCall(event=event, started=time.perf_counter())
        return attempt_id

    def finish_attempt(
        self,
        attempt_id: uuid.UUID,
        *,
        status: str,
        error: BaseException | None = None,
    ) -> None:
        active = self._active.pop(attempt_id, None)
        if active is None:
            return
        active.event.status = status
        active.event.latency_ms = max(0, round((time.perf_counter() - active.started) * 1000))
        if error is not None:
            active.event.error_category, active.event.error_status = classify_error(error)


def current_trace() -> OnboardingTraceSink | None:
    return _CURRENT_TRACE.get()


def current_call_id() -> uuid.UUID | None:
    return _CURRENT_CALL.get()


@contextmanager
def use_trace(sink: OnboardingTraceSink) -> Iterator[None]:
    trace_token = _CURRENT_TRACE.set(sink)
    try:
        yield
    finally:
        _CURRENT_TRACE.reset(trace_token)


@contextmanager
def use_call(call_id: uuid.UUID) -> Iterator[None]:
    token = _CURRENT_CALL.set(call_id)
    try:
        yield
    finally:
        _CURRENT_CALL.reset(token)
