from __future__ import annotations

from typing import Any

from app.repositories import UnitOfWork
from app.services.health import HealthService
from app.services.knowledge import KnowledgeService
from app.services.runtimes import RuntimeService
from app.services.runtime_assistant.schemas import DiagnosticResult


class RuntimeDiagnostics:
    def __init__(self, uow: UnitOfWork, runtime_id: str, user_id: str) -> None:
        self.uow = uow
        self.runtime_id = runtime_id
        self.user_id = user_id
        self.runtime_service = RuntimeService(uow)
        self.health_service = HealthService(uow)
        self.knowledge_service = KnowledgeService(uow)

    async def diagnose_slow_runtime(self) -> list[DiagnosticResult]:
        results: list[DiagnosticResult] = []
        health = await self.health_service.get_runtime_health(self.runtime_id)
        runtime = await self.runtime_service.get(self.runtime_id)
        if not runtime:
            return results

        llm_latency = health.get("llm_latency_ms", 0)
        embedding_latency = health.get("embedding_latency_ms", 0)
        retrieval_latency = health.get("retrieval_latency_ms", 0)
        queue_depth = health.get("worker_queue_depth", 0)
        cache_hit_rate = health.get("cache_hit_rate", 0)

        if llm_latency > 3000:
            results.append(
                DiagnosticResult(
                    issue="High LLM latency",
                    severity="warning",
                    description=f"LLM latency is {llm_latency:.0f}ms, which is above the 3s threshold.",
                    affected_components=["model", "provider"],
                    recommendations=[
                        "Switch to a faster model for simple tasks",
                        "Enable dynamic routing",
                        "Consider using a faster provider",
                    ],
                    metrics={"llm_latency_ms": llm_latency},
                )
            )

        if embedding_latency > 2000:
            results.append(
                DiagnosticResult(
                    issue="Slow embedding generation",
                    severity="warning",
                    description=f"Embedding latency is {embedding_latency:.0f}ms.",
                    affected_components=["embeddings", "vector_store"],
                    recommendations=[
                        "Pre-compute embeddings",
                        "Use a faster embedding model",
                        "Increase batch size",
                    ],
                    metrics={"embedding_latency_ms": embedding_latency},
                )
            )

        if retrieval_latency > 1000:
            results.append(
                DiagnosticResult(
                    issue="Slow retrieval",
                    severity="warning",
                    description=f"Retrieval latency is {retrieval_latency:.0f}ms.",
                    affected_components=["vector_store", "retrieval"],
                    recommendations=[
                        "Optimize vector index",
                        "Reduce chunk count",
                        "Enable query caching",
                    ],
                    metrics={"retrieval_latency_ms": retrieval_latency},
                )
            )

        if queue_depth > 0:
            results.append(
                DiagnosticResult(
                    issue="Worker queue backlog",
                    severity="warning",
                    description=f"Worker queue has depth {queue_depth}.",
                    affected_components=["runtime", "workers"],
                    recommendations=[
                        "Scale workers",
                        "Review recent build jobs",
                    ],
                    metrics={"worker_queue_depth": queue_depth},
                )
            )

        if cache_hit_rate and cache_hit_rate < 30:
            results.append(
                DiagnosticResult(
                    issue="Low cache hit rate",
                    severity="info",
                    description=f"Cache hit rate is {cache_hit_rate:.1f}%.",
                    affected_components=["cache"],
                    recommendations=[
                        "Increase cache TTL",
                        "Review cache invalidation strategy",
                        "Warm cache for common queries",
                    ],
                    metrics={"cache_hit_rate": cache_hit_rate},
                )
            )

        model = runtime.get("model", "")
        if "gpt-4" in model or "claude-3" in model or "claude-2" in model:
            results.append(
                DiagnosticResult(
                    issue="Expensive model in use",
                    severity="info",
                    description=f"Using {model} which is a high-cost model.",
                    affected_components=["model"],
                    recommendations=[
                        "Use cheaper models for simple tasks",
                        "Enable dynamic routing",
                        "Consider Haiku or GPT-3.5 for lightweight queries",
                    ],
                    metrics={"model": model},
                )
            )

        return results

    async def diagnose_expensive_runtime(self) -> list[DiagnosticResult]:
        results: list[DiagnosticResult] = []
        from app.services.billing import BillingService

        billing_service = BillingService(self.uow.session)
        summary = await billing_service.get_usage_summary(uuid.UUID(self.user_id) if self.user_id else None)

        total_cost = summary.get("total_cost", 0)
        if hasattr(total_cost, "__float__"):
            total_cost = float(total_cost)

        if total_cost > 100:
            results.append(
                DiagnosticResult(
                    issue="High monthly cost",
                    severity="warning",
                    description=f"Monthly cost is ${total_cost:.2f}.",
                    affected_components=["billing", "models"],
                    recommendations=[
                        "Review model usage patterns",
                        "Enable dynamic routing",
                        "Downgrade models for simple tasks",
                    ],
                    metrics={"total_cost": total_cost},
                )
            )

        by_model = summary.get("by_model", [])
        if by_model:
            top_model = max(by_model, key=lambda x: x.get("cost", 0) or 0)
            if top_model and (top_model.get("cost", 0) or 0) > 50:
                results.append(
                    DiagnosticResult(
                        issue="Expensive model dominating",
                        severity="warning",
                        description=f"Model {top_model.get('model')} accounts for ${top_model.get('cost', 0):.2f} in costs.",
                        affected_components=["model"],
                        recommendations=[
                            f"Consider alternatives to {top_model.get('model')}",
                            "Enable dynamic routing to mix models",
                        ],
                        metrics=top_model,
                    )
                )

        return results

    async def diagnose_inaccurate_answers(self) -> list[DiagnosticResult]:
        results: list[DiagnosticResult] = []
        runtime = await self.runtime_service.get(self.runtime_id)
        if not runtime:
            return results

        sources = await self.knowledge_service.list_sources(runtime.get("project_id", ""))
        failed_sources = [s for s in sources if s.get("status") in ("error", "failed")]

        if failed_sources:
            results.append(
                DiagnosticResult(
                    issue="Failed knowledge sources",
                    severity="error",
                    description=f"{len(failed_sources)} knowledge source(s) have failed.",
                    affected_components=["knowledge"],
                    recommendations=[
                        "Reconnect failed sources",
                        "Check credentials",
                        "Review sync logs",
                    ],
                    metrics={"failed_sources": len(failed_sources)},
                )
            )

        health = await self.health_service.get_runtime_health(self.runtime_id)
        retrieval_quality = health.get("retrieval_quality")
        if retrieval_quality is not None and retrieval_quality < 0.6:
            results.append(
                DiagnosticResult(
                    issue="Low retrieval quality",
                    severity="warning",
                    description=f"Retrieval quality is {retrieval_quality:.2f}.",
                    affected_components=["retrieval", "embeddings"],
                    recommendations=[
                        "Review chunk size settings",
                        "Improve embedding model",
                        "Add more diverse sources",
                    ],
                    metrics={"retrieval_quality": retrieval_quality},
                )
            )

        return results

    async def diagnose_sync_failures(self) -> list[DiagnosticResult]:
        results: list[DiagnosticResult] = []
        runtime = await self.runtime_service.get(self.runtime_id)
        if not runtime:
            return results

        sources = await self.knowledge_service.list_sources(runtime.get("project_id", ""))
        failed_sources = [s for s in sources if s.get("status") in ("error", "failed")]

        for source in failed_sources:
            results.append(
                DiagnosticResult(
                    issue=f"Sync failed: {source.get('display_name')}",
                    severity="error",
                    description=source.get("last_error") or "Unknown error",
                    affected_components=["knowledge", source.get("source_type", "unknown")],
                    recommendations=[
                        "Check credentials",
                        "Verify source connectivity",
                        "Review rate limits",
                    ],
                    metrics={
                        "source_id": source.get("id"),
                        "error_count": source.get("error_count", 0),
                    },
                )
            )

        return results

    async def run_full_diagnostics(self) -> list[DiagnosticResult]:
        all_results: list[DiagnosticResult] = []
        all_results.extend(await self.diagnose_slow_runtime())
        all_results.extend(await self.diagnose_expensive_runtime())
        all_results.extend(await self.diagnose_inaccurate_answers())
        all_results.extend(await self.diagnose_sync_failures())
        return all_results
