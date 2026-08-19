from __future__ import annotations

import uuid

import pytest

from app.api.v1.runtimes.router import _build_topology
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
