from __future__ import annotations

import uuid

import pytest

from app.api.v1.runtimes.router import _build_topology
from app.models.request_logs import RequestLog
from app.models.runtimes import Runtime
from app.models.users import User


@pytest.mark.asyncio
async def test_runtime_topology_uses_runtime_configuration_and_integrations(db_session):
    user = User(email=f"topology-{uuid.uuid4().hex}@example.com", name="Topology Test", is_active=True, email_verified=True)
    db_session.add(user)
    await db_session.flush()
    runtime = Runtime(
        user_id=user.id,
        name="Topology Runtime",
        provider="openai",
        model="gpt-4o-mini",
        routing_strategy="balanced",
        fallback_models=["claude-3-5-sonnet"],
        vector_store="pgvector",
        status="active",
        health=92.5,
    )
    db_session.add(runtime)
    await db_session.commit()

    topology = await _build_topology(runtime, db_session)
    assert topology["simulated"] is False
    assert {node.id for node in topology["nodes"]} >= {"application", "runtime", "router", "model", "knowledge", "vector_store"}
    assert topology["routing"]["provider"] == "openai"
    assert topology["telemetry"]["requests_24h"] == 0
    assert topology["telemetry"]["error_rate"] is None
    statuses = {node.id: node.status for node in topology["nodes"]}
    assert statuses["application"] == "idle"
    assert statuses["model"] == "configured"
    assert statuses["knowledge"] == "unconfigured"


@pytest.mark.asyncio
async def test_topology_simulation_is_explicit_and_does_not_change_runtime(db_session):
    user = User(email=f"simulation-{uuid.uuid4().hex}@example.com", name="Simulation Test", is_active=True, email_verified=True)
    db_session.add(user)
    await db_session.flush()
    runtime = Runtime(
        user_id=user.id,
        name="Simulation Runtime",
        provider="openai",
        model="gpt-4o-mini",
        fallback_models=["claude-3-5-sonnet"],
        vector_store="pgvector",
        status="active",
    )
    db_session.add(runtime)
    await db_session.commit()

    topology = await _build_topology(runtime, db_session, simulation="llm_failover")
    assert topology["simulated"] is True
    assert topology["routing"]["simulation_mode"] == "llm_failover"
    assert runtime.status == "active"
    assert any(node.metadata.get("fallback") for node in topology["nodes"])


@pytest.mark.asyncio
async def test_runtime_topology_counts_successes_and_failures_from_request_outcomes(
    db_session,
):
    user = User(
        email=f"outcomes-{uuid.uuid4().hex}@example.com",
        name="Outcome Test",
        is_active=True,
        email_verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    runtime = Runtime(
        user_id=user.id,
        name="Outcome Runtime",
        provider="google",
        model="gemini-2.5-flash",
        vector_store="pgvector",
        status="active",
    )
    db_session.add(runtime)
    await db_session.flush()
    db_session.add_all(
        [
            RequestLog(
                runtime_id=runtime.id,
                request_id=f"req_{uuid.uuid4().hex}",
                method="POST",
                endpoint="/invoke",
                status=200,
                latency_ms=410,
            ),
            RequestLog(
                runtime_id=runtime.id,
                request_id=f"req_{uuid.uuid4().hex}",
                method="POST",
                endpoint="/invoke",
                status=403,
                error_category="ip_blocked",
                latency_ms=12,
            ),
            RequestLog(
                runtime_id=runtime.id,
                request_id=f"req_{uuid.uuid4().hex}",
                method="POST",
                endpoint="/invoke",
                status=502,
                error_category="provider_unavailable",
                latency_ms=820,
            ),
        ]
    )
    await db_session.commit()

    topology = await _build_topology(runtime, db_session)

    telemetry = topology["telemetry"]
    assert telemetry["requests_24h"] == 3
    assert telemetry["errors_24h"] == 2
    assert telemetry["rejected_requests_24h"] == 1
    assert telemetry["server_errors_24h"] == 1
    assert telemetry["error_rate"] == pytest.approx(2 / 3, abs=0.000001)
    assert telemetry["errors_by_category"] == {
        "ip_blocked": 1,
        "provider_unavailable": 1,
    }
