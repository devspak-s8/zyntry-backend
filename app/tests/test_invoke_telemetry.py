from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import pytest
from fastapi import Request
from sqlalchemy import select

from app.models.events import Event
from app.models.request_logs import RequestLog
from app.repositories import UnitOfWork
from app.services import invoke_telemetry
from app.services.invoke_telemetry import (
    begin_invoke_telemetry,
    classify_invoke_error,
    persist_invoke_outcome,
    update_invoke_telemetry,
)
from app.services.observability import ObservabilityService


def make_request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/invoke",
            "headers": [],
        }
    )


@pytest.mark.parametrize(
    ("status_code", "detail", "expected"),
    [
        (403, {"code": "ip_blocked", "message": "safe"}, "ip_blocked"),
        (429, "Too many requests", "rate_limited"),
        (502, "Provider failed", "provider_unavailable"),
        (500, None, "internal_error"),
    ],
)
def test_classify_invoke_error(status_code, detail, expected):
    assert classify_invoke_error(status_code, detail) == expected


@pytest.mark.asyncio
async def test_persist_invoke_outcome_records_failed_runtime_request(monkeypatch, db_session):
    @asynccontextmanager
    async def session_factory():
        yield db_session

    monkeypatch.setattr(invoke_telemetry, "async_session_factory", session_factory)
    runtime_id = uuid.uuid4()
    project_id = uuid.uuid4()
    request = make_request()
    begin_invoke_telemetry(request, "req_failed_telemetry")
    update_invoke_telemetry(
        request,
        runtime_id=runtime_id,
        project_id=project_id,
        provider="google",
        model="gemini-2.5-flash",
    )

    await persist_invoke_outcome(
        request,
        status_code=502,
        detail="All configured providers failed",
    )
    # A second terminal path for the same request must not double count it.
    await persist_invoke_outcome(request, status_code=500)

    logs = list((await db_session.execute(select(RequestLog))).scalars().all())
    events = list((await db_session.execute(select(Event))).scalars().all())

    assert len(logs) == 1
    assert logs[0].runtime_id == runtime_id
    assert logs[0].project_id == project_id
    assert logs[0].status == 502
    assert logs[0].error_category == "provider_unavailable"
    assert len(events) == 1
    assert events[0].event_type == "runtime.execution.failed"
    assert events[0].data["status_code"] == 502

    summary = await ObservabilityService(UnitOfWork(db_session)).get_observability_summary(
        str(runtime_id)
    )
    assert summary["request_count"] == 1
    assert summary["success_count"] == 0
    assert summary["error_count"] == 1
    assert summary["server_error_count"] == 1
    assert summary["rejected_request_count"] == 0
    assert summary["error_rate"] == 1.0
    assert summary["errors_by_category"] == {"provider_unavailable": 1}
