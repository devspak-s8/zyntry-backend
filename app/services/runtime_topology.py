"""Runtime topology and telemetry projection.

Topology is a read-only view over runtime, usage, request, and integration
records.  Keeping the projection outside the HTTP router makes it reusable
from the console API, background diagnostics, and contract tests.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing import UsageLog
from app.models.integrations import RuntimeIntegration
from app.models.request_logs import RequestLog
from app.models.runtimes import Runtime
from app.schemas.runtimes import RuntimeTopologyEdge, RuntimeTopologyNode


async def build_runtime_topology(
    runtime: Runtime,
    db: AsyncSession,
    *,
    simulation: str | None = None,
) -> dict[str, Any]:
    """Build a 24-hour runtime topology projection from persisted telemetry."""
    now = datetime.now(UTC)
    since = now - timedelta(hours=24)
    usage_rows = list(
        (
            await db.execute(
                select(UsageLog).where(
                    UsageLog.runtime_id == runtime.id,
                    UsageLog.created_at >= since,
                )
            )
        )
        .scalars()
        .all()
    )
    request_rows = []
    if runtime.project_id:
        request_rows = list(
            (
                await db.execute(
                    select(RequestLog).where(
                        RequestLog.project_id == runtime.project_id,
                        RequestLog.created_at >= since,
                    )
                )
            )
            .scalars()
            .all()
        )

    latencies = sorted(float(row.latency_ms) for row in usage_rows if row.latency_ms is not None)
    p95 = (
        latencies[min(len(latencies) - 1, max(0, int(len(latencies) * 0.95) - 1))]
        if latencies
        else None
    )
    total_requests = sum(int(row.requests or 1) for row in usage_rows)
    total_tokens = sum(
        int(row.input_tokens or 0) + int(row.output_tokens or 0) for row in usage_rows
    )
    total_cost = sum(float(row.cost or 0) for row in usage_rows)
    errors = sum(1 for row in request_rows if int(row.status or 0) >= 400)
    provider_counts = Counter(row.provider for row in usage_rows if row.provider)
    model_counts = Counter(row.model for row in usage_rows if row.model)
    integrations = list(
        (
            await db.execute(
                select(RuntimeIntegration).where(RuntimeIntegration.runtime_id == runtime.id)
            )
        )
        .scalars()
        .all()
    )

    telemetry = {
        "requests_24h": total_requests,
        "tokens_24h": total_tokens,
        "cost_24h": round(total_cost, 8),
        "errors_24h": errors,
        "error_rate": round(errors / max(1, len(request_rows)), 6),
        "average_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else None,
        "p95_latency_ms": p95,
        "providers": dict(provider_counts),
        "models": dict(model_counts),
    }

    node_status = {
        "application": "active",
        "runtime": runtime.status,
        "router": "active",
        "model": "active" if runtime.provider and runtime.model else "unconfigured",
        "knowledge": "ready" if runtime.embeddings or runtime.documents == 0 else "indexing",
        "vector_store": "active" if runtime.vector_store else "unconfigured",
    }
    simulated = simulation is not None
    if simulation == "postgres_degraded":
        node_status["vector_store"] = "degraded"
        node_status["knowledge"] = "degraded"
    elif simulation == "traffic_surge":
        node_status["application"] = "pressured"
        node_status["router"] = "balancing"
    elif simulation == "llm_failover":
        node_status["model"] = "failed_over"

    nodes = [
        RuntimeTopologyNode(
            id="application",
            kind="application",
            label="Your Application",
            status=node_status["application"],
            metrics={"requests_24h": total_requests, "error_rate": telemetry["error_rate"]},
            simulated=simulated,
        ),
        RuntimeTopologyNode(
            id="runtime",
            kind="runtime",
            label=runtime.name,
            status=node_status["runtime"],
            health=float(runtime.health or 0),
            metrics={
                "documents": runtime.documents,
                "chunks": runtime.chunks,
                "embeddings": runtime.embeddings,
                "index_size": runtime.index_size,
            },
            simulated=simulated,
        ),
        RuntimeTopologyNode(
            id="router",
            kind="router",
            label="AI Router",
            status=node_status["router"],
            metrics={"strategy": runtime.routing_strategy, "p95_latency_ms": p95},
            simulated=simulated,
        ),
        RuntimeTopologyNode(
            id="model",
            kind="model",
            label=f"{runtime.provider or 'Unassigned'} / {runtime.model or 'Unassigned'}",
            status=node_status["model"],
            metrics={
                "average_latency_ms": telemetry["average_latency_ms"],
                "requests_24h": provider_counts.get(runtime.provider, 0),
            },
            metadata={"provider": runtime.provider, "model": runtime.model},
            simulated=simulated,
        ),
        RuntimeTopologyNode(
            id="knowledge",
            kind="knowledge",
            label="Indexed Knowledge",
            status=node_status["knowledge"],
            metrics={
                "documents": runtime.documents,
                "chunks": runtime.chunks,
                "embeddings": runtime.embeddings,
            },
            simulated=simulated,
        ),
        RuntimeTopologyNode(
            id="vector_store",
            kind="vector_store",
            label=runtime.vector_store or "Vector Store",
            status=node_status["vector_store"],
            metrics={"index_size": runtime.index_size},
            simulated=simulated,
        ),
    ]
    for integration in integrations:
        nodes.append(
            RuntimeTopologyNode(
                id=f"integration:{integration.integration_slug}",
                kind="integration",
                label=integration.integration_slug,
                status=integration.connection_status if integration.is_enabled else "disabled",
                metadata={
                    "capabilities": integration.enabled_capabilities or [],
                    "connection_mode": integration.connection_mode,
                },
                simulated=simulated,
            )
        )

    edges = [
        RuntimeTopologyEdge(source="application", target="runtime"),
        RuntimeTopologyEdge(source="runtime", target="router"),
        RuntimeTopologyEdge(
            source="router",
            target="model",
            status="degraded" if simulation == "llm_failover" else "active",
        ),
        RuntimeTopologyEdge(source="runtime", target="knowledge"),
        RuntimeTopologyEdge(
            source="knowledge",
            target="vector_store",
            status="degraded" if simulation == "postgres_degraded" else "active",
        ),
    ]
    edges.extend(
        RuntimeTopologyEdge(source="router", target=f"integration:{item.integration_slug}")
        for item in integrations
        if item.is_enabled
    )
    fallback_models = list(runtime.fallback_models or [])
    if simulation == "llm_failover":
        for index, fallback in enumerate(fallback_models):
            node_id = f"fallback:{index}"
            nodes.append(
                RuntimeTopologyNode(
                    id=node_id,
                    kind="model",
                    label=fallback,
                    status="active",
                    metadata={"fallback": True},
                    simulated=True,
                )
            )
            edges.append(
                RuntimeTopologyEdge(
                    source="router",
                    target=node_id,
                    metadata={"selected": index == 0, "reason": "simulated primary failure"},
                )
            )

    return {
        "runtime_id": runtime.id,
        "project_id": runtime.project_id,
        "generated_at": now,
        "window_seconds": 86400,
        "simulated": simulated,
        "nodes": nodes,
        "edges": edges,
        "routing": {
            "strategy": runtime.routing_strategy,
            "provider": runtime.provider,
            "model": runtime.model,
            "fallback_models": fallback_models,
            "failover_enabled": True,
            "simulation_mode": simulation,
        },
        "telemetry": telemetry,
    }
