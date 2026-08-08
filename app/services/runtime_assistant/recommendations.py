from __future__ import annotations

from typing import Any

from app.repositories import UnitOfWork
from app.services.billing import BillingService
from app.services.health import HealthService
from app.services.knowledge import KnowledgeService
from app.services.runtimes import RuntimeService
from app.services.runtime_assistant.optimizer import RuntimeOptimizer
from app.services.runtime_assistant.schemas import OptimizationResult


class RuntimeRecommendations:
    def __init__(self, uow: UnitOfWork, runtime_id: str, user_id: str) -> None:
        self.uow = uow
        self.runtime_id = runtime_id
        self.user_id = user_id
        self.runtime_service = RuntimeService(uow)
        self.health_service = HealthService(uow)
        self.knowledge_service = KnowledgeService(uow)
        self.billing_service = BillingService(uow.session)

    async def generate(self) -> list[OptimizationResult]:
        optimizer = RuntimeOptimizer(self.uow, self.runtime_id, self.user_id)
        all_optimizations = await optimizer.optimize_all()
        flat: list[OptimizationResult] = []
        for category_results in all_optimizations.values():
            flat.extend(category_results)
        flat.sort(key=lambda x: {"high": 0, "medium": 1, "low": 2}.get(x.priority, 1))
        return flat

    async def generate_cost_recommendations(self) -> list[OptimizationResult]:
        optimizer = RuntimeOptimizer(self.uow, self.runtime_id, self.user_id)
        return await optimizer.optimize_cost()

    async def generate_latency_recommendations(self) -> list[OptimizationResult]:
        optimizer = RuntimeOptimizer(self.uow, self.runtime_id, self.user_id)
        return await optimizer.optimize_latency()

    async def generate_security_recommendations(self) -> list[OptimizationResult]:
        optimizer = RuntimeOptimizer(self.uow, self.runtime_id, self.user_id)
        return await optimizer.optimize_security()

    async def generate_knowledge_recommendations(self) -> list[OptimizationResult]:
        optimizer = RuntimeOptimizer(self.uow, self.runtime_id, self.user_id)
        return await optimizer.optimize_knowledge()

    async def format_recommendations(self, recommendations: list[OptimizationResult]) -> str:
        if not recommendations:
            return "Your runtime is well optimized. No immediate recommendations."

        lines = [f"I found {len(recommendations)} optimization opportunity(ies).\n"]
        for rec in recommendations:
            lines.append(f"• {rec.title}")
            lines.append(f"  {rec.description}")
            if rec.estimated_savings:
                lines.append(f"  Estimated impact: {rec.estimated_savings}")
            lines.append("")

        return "\n".join(lines)
