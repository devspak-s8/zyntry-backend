from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from functools import wraps
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.core.database import async_session_factory
from app.models.events import Event
from app.models.request_logs import RequestLog

logger = logging.getLogger(__name__)


def begin_invoke_telemetry(request: Request, request_id: str) -> dict[str, Any]:
    context: dict[str, Any] = {
        "request_id": request_id,
        "started_at": datetime.now(UTC),
        "started_perf": time.perf_counter(),
        "project_id": None,
        "runtime_id": None,
        "organization_id": None,
        "user_id": None,
        "api_key_id": getattr(request.state, "api_key_id", None),
        "provider": None,
        "model": None,
    }
    request.state.invoke_telemetry = context
    return context


def update_invoke_telemetry(request: Request, **values: Any) -> None:
    context = getattr(request.state, "invoke_telemetry", None)
    if isinstance(context, dict):
        context.update({key: value for key, value in values.items() if value is not None})


def classify_invoke_error(status_code: int, detail: Any = None) -> str:
    if isinstance(detail, dict) and detail.get("code"):
        return str(detail["code"])[:64]
    if status_code == 400:
        return "invalid_request"
    if status_code == 401:
        return "authentication_failed"
    if status_code == 402:
        return "billing_rejected"
    if status_code == 403:
        return "authorization_rejected"
    if status_code == 404:
        return "resource_unavailable"
    if status_code == 409:
        return "runtime_conflict"
    if status_code == 422:
        return "validation_failed"
    if status_code == 429:
        return "rate_limited"
    if status_code == 502:
        return "provider_unavailable"
    if status_code == 503:
        return "service_unavailable"
    if status_code >= 500:
        return "internal_error"
    return "request_failed"


async def persist_invoke_outcome(
    request: Request,
    *,
    status_code: int,
    detail: Any = None,
    response: Any = None,
) -> None:
    """Persist one non-billable terminal reliability record per invocation."""
    context = getattr(request.state, "invoke_telemetry", None)
    if not isinstance(context, dict) or context.get("persisted"):
        return
    # A failure cannot be attributed to a runtime until both ownership
    # boundaries have been resolved by the invoke handler.
    if context.get("project_id") is None or context.get("runtime_id") is None:
        return
    context["persisted"] = True

    if response is not None:
        context["provider"] = getattr(response, "provider", None) or context.get("provider")
        context["model"] = getattr(response, "model", None) or context.get("model")
        context["tokens"] = getattr(response, "tokens_used", None)
        context["cost"] = getattr(response, "actual_cost", None)

    completed_at = datetime.now(UTC)
    latency_ms = max(0, int((time.perf_counter() - context["started_perf"]) * 1000))
    failed = status_code >= 400
    error_category = classify_invoke_error(status_code, detail) if failed else None

    try:
        async with async_session_factory() as session:
            existing = await session.scalar(
                select(RequestLog.id).where(RequestLog.request_id == context["request_id"])
            )
            if existing is not None:
                return
            session.add(
                RequestLog(
                    project_id=context["project_id"],
                    runtime_id=context["runtime_id"],
                    request_id=context["request_id"],
                    method="POST",
                    endpoint="/invoke",
                    status=status_code,
                    error_category=error_category,
                    latency_ms=latency_ms,
                    tokens=context.get("tokens"),
                    provider=context.get("provider"),
                    model=context.get("model"),
                    # Billing precision remains in UsageLog; this legacy field
                    # is retained only for RequestLog contract compatibility.
                    cost=int(float(context.get("cost") or 0)),
                    started_at=context["started_at"].isoformat(),
                    completed_at=completed_at.isoformat(),
                    user_id=context.get("user_id"),
                    ip=None,
                )
            )
            if failed:
                session.add(
                    Event(
                        project_id=context["project_id"],
                        organization_id=context.get("organization_id"),
                        event_type="runtime.execution.failed",
                        data={
                            "request_id": context["request_id"],
                            "runtime_id": str(context["runtime_id"]),
                            "provider": context.get("provider"),
                            "model": context.get("model"),
                            "status_code": status_code,
                            "error_category": error_category,
                            "latency_ms": latency_ms,
                        },
                    )
                )
            await session.commit()
    except Exception:
        # Observability must never replace the original invocation outcome.
        logger.exception(
            "Unable to persist terminal invocation telemetry",
            extra={"request_id": context.get("request_id"), "status_code": status_code},
        )


async def record_invoke_exception(request: Request, exc: Exception) -> None:
    if isinstance(exc, HTTPException):
        await persist_invoke_outcome(
            request,
            status_code=exc.status_code,
            detail=exc.detail,
        )
        return
    await persist_invoke_outcome(request, status_code=500, detail=None)


def record_invoke_outcome[**P, R](
    handler: Callable[P, Awaitable[R]],
) -> Callable[P, Awaitable[R]]:
    """Decorate the invoke handler without changing its FastAPI signature."""

    @wraps(handler)
    async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        request_value = kwargs.get("request")
        request = request_value if isinstance(request_value, Request) else None
        if request is None:
            request = next((item for item in args if isinstance(item, Request)), None)
        if request is None:
            return await handler(*args, **kwargs)

        begin_invoke_telemetry(request, f"req_{uuid.uuid4().hex[:12]}")
        try:
            result = await handler(*args, **kwargs)
        except Exception as exc:
            await record_invoke_exception(request, exc)
            raise

        # Streaming responses complete later. Their internal non-streaming
        # invocation passes through this decorator again and records the true
        # terminal result after provider execution finishes.
        if not isinstance(result, StreamingResponse):
            await persist_invoke_outcome(request, status_code=200, response=result)
        return result

    return wrapped
