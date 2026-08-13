from __future__ import annotations

import uuid
from typing import Any

from app.repositories import UnitOfWork
from app.services.billing import BillingService
from app.services.health import HealthService
from app.services.knowledge import KnowledgeService
from app.services.runtimes import RuntimeService
from app.services.runtime_assistant.schemas import OptimizationResult


class RuntimeOptimizer:
    def __init__(self, uow: UnitOfWork, runtime_id: str, user_id: str) -> None:
        self.uow = uow
        self.runtime_id = runtime_id
        self.user_id = user_id
        self.runtime_service = RuntimeService(uow)
        self.health_service = HealthService(uow)
        self.knowledge_service = KnowledgeService(uow)

    async def optimize_cost(self) -> list[OptimizationResult]:
        results: list[OptimizationResult] = []
        billing_service = BillingService(self.uow.session)
        summary = await billing_service.get_usage_summary(
            uuid.UUID(self.user_id) if self.user_id else None
        )

        total_cost = summary.get("total_cost", 0)
        if hasattr(total_cost, "__float__"):
            total_cost = float(total_cost)

        if total_cost > 50:
            results.append(
                OptimizationResult(
                    category="cost",
                    title="Enable Dynamic Routing",
                    description="Dynamic routing automatically selects cheaper models for simple tasks, reducing costs by 20-40%.",
                    impact="high",
                    estimated_savings="20-40%",
                    actions=["enable_dynamic_routing"],
                    priority="high",
                )
            )

        by_model = summary.get("by_model", [])
        if isinstance(by_model, dict):
            by_model = [
                {"model": model, "cost": cost}
                for model, cost in by_model.items()
            ]
        elif not isinstance(by_model, list):
            by_model = []
        by_model = [entry for entry in by_model if isinstance(entry, dict)]
        if by_model:
            top_model = max(by_model, key=lambda x: x.get("cost", 0) or 0)
            if top_model and (top_model.get("cost", 0) or 0) > 30:
                model_name = top_model.get("model", "unknown")
                results.append(
                    OptimizationResult(
                        category="cost",
                        title=f"Downgrade {model_name} for simple tasks",
                        description=f"Model {model_name} is expensive. Use cheaper alternatives for simple queries.",
                        impact="high",
                        estimated_savings="15-30%",
                        actions=["change_default_provider", "enable_dynamic_routing"],
                        priority="high",
                    )
                )

        return results

    async def optimize_latency(self) -> list[OptimizationResult]:
        results: list[OptimizationResult] = []
        health = await self.health_service.get_runtime_health(self.runtime_id)

        llm_latency = health.get("llm_latency_ms", 0)
        embedding_latency = health.get("embedding_latency_ms", 0)
        cache_hit_rate = health.get("cache_hit_rate", 0)

        if llm_latency > 2000:
            results.append(
                OptimizationResult(
                    category="latency",
                    title="Switch to faster model",
                    description=f"LLM latency is {llm_latency:.0f}ms. Consider faster alternatives.",
                    impact="high",
                    estimated_savings="50-70% latency",
                    actions=["change_default_provider"],
                    priority="high",
                )
            )

        if embedding_latency > 1000:
            results.append(
                OptimizationResult(
                    category="latency",
                    title="Optimize embedding generation",
                    description=f"Embedding latency is {embedding_latency:.0f}ms. Pre-compute embeddings.",
                    impact="medium",
                    estimated_savings="30-50% embedding latency",
                    actions=["rebuild_embeddings"],
                    priority="medium",
                )
            )

        if cache_hit_rate and cache_hit_rate < 40:
            results.append(
                OptimizationResult(
                    category="latency",
                    title="Improve cache hit rate",
                    description=f"Cache hit rate is {cache_hit_rate:.1f}%. Increase TTL and warm cache.",
                    impact="medium",
                    estimated_savings="20-40% retrieval latency",
                    actions=["clear_cache"],
                    priority="medium",
                )
            )

        return results

    async def optimize_security(self) -> list[OptimizationResult]:
        results: list[OptimizationResult] = []
        try:
            from app.services.apikeys import ApiKeyService

            api_key_service = ApiKeyService(self.uow)
            runtime = await self.runtime_service.get(self.runtime_id)
            if not runtime:
                return results

            api_key_id = runtime.get("api_key_id")
            if api_key_id:
                key = await self.uow.api_keys.get(api_key_id)
                if key:
                    results.append(
                        OptimizationResult(
                            category="security",
                            title="Rotate API key",
                            description="Regular key rotation improves security posture.",
                            impact="medium",
                            estimated_savings=None,
                            actions=["rotate_api_key"],
                            priority="medium",
                        )
                    )
        except Exception:
            pass
        return results

    async def optimize_knowledge(self) -> list[OptimizationResult]:
        results: list[OptimizationResult] = []
        runtime = await self.runtime_service.get(self.runtime_id)
        if not runtime:
            return results

        sources = await self.knowledge_service.list_sources(runtime.get("project_id", ""))
        failed_sources = [s for s in sources if s.get("status") in ("error", "failed")]

        if failed_sources:
            results.append(
                OptimizationResult(
                    category="knowledge",
                    title="Reconnect failed knowledge sources",
                    description=f"{len(failed_sources)} source(s) have failed. Reconnect them to restore coverage.",
                    impact="high",
                    estimated_savings=None,
                    actions=["sync_sources"],
                    priority="high",
                )
            )

        health = await self.health_service.get_runtime_health(self.runtime_id)
        retrieval_quality = health.get("retrieval_quality")
        if retrieval_quality is not None and retrieval_quality < 0.6:
            results.append(
                OptimizationResult(
                    category="knowledge",
                    title="Improve retrieval quality",
                    description=f"Retrieval quality is {retrieval_quality:.2f}. Review chunk settings and sources.",
                    impact="high",
                    estimated_savings=None,
                    actions=["rebuild_embeddings"],
                    priority="high",
                )
            )

        return results

    async def optimize_all(self) -> dict[str, list[OptimizationResult]]:
        return {
            "cost": await self.optimize_cost(),
            "latency": await self.optimize_latency(),
            "security": await self.optimize_security(),
            "knowledge": await self.optimize_knowledge(),
        }
