from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.core.config import settings
from app.services.model_providers.base import ModelInfo
from app.services.model_providers import PROVIDER_REGISTRY


class RoutingGoal(str, Enum):
    FASTEST = "fastest"
    CHEAPEST = "cheapest"
    BALANCED = "balanced"
    REASONING = "reasoning"
    CODING = "coding"
    VISION = "vision"
    LONG_CONTEXT = "long_context"


@dataclass
class RoutingPreference:
    goal: RoutingGoal = RoutingGoal.BALANCED
    preferred_providers: list[str] = field(default_factory=list)
    excluded_providers: list[str] = field(default_factory=list)
    max_latency_ms: int | None = None
    max_cost_per_1k: float | None = None
    min_context: int | None = None
    requires_vision: bool = False
    requires_tools: bool = False
    requires_streaming: bool = False


@dataclass
class ModelCandidate:
    model_info: ModelInfo
    provider_name: str
    score: float = 0.0
    latency_ms: float | None = None
    available: bool = True
    error: str | None = None


class ModelRouter:
    PROVIDER_PRIORITY: dict[RoutingGoal, list[str]] = {
        RoutingGoal.CODING: ["anthropic", "openai", "deepseek", "groq"],
        RoutingGoal.FASTEST: ["groq", "deepseek", "openrouter", "openai"],
        RoutingGoal.CHEAPEST: ["deepseek", "groq", "openrouter", "mistral"],
        RoutingGoal.REASONING: ["anthropic", "openai", "deepseek"],
        RoutingGoal.BALANCED: ["openai", "anthropic", "groq", "deepseek"],
        RoutingGoal.VISION: ["openai", "anthropic", "google"],
        RoutingGoal.LONG_CONTEXT: ["anthropic", "openai", "deepseek"],
    }

    def __init__(self, uow: Any) -> None:
        self.uow = uow

    async def route(self, preference: RoutingPreference, available_providers: dict[str, str]) -> ModelCandidate | None:
        candidates = await self._build_candidates(preference, available_providers)
        if not candidates:
            return None
        candidates = [c for c in candidates if c.available]
        if not candidates:
            return None
        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates[0]

    async def _build_candidates(self, preference: RoutingPreference, available_providers: dict[str, str]) -> list[ModelCandidate]:
        candidates: list[ModelCandidate] = []
        provider_priority = self.PROVIDER_PRIORITY.get(preference.goal, self.PROVIDER_PRIORITY[RoutingGoal.BALANCED])
        ordered_providers = sorted(
            [p for p in provider_priority if p in available_providers and p not in preference.excluded_providers],
            key=lambda p: provider_priority.index(p) if p in provider_priority else 999,
        )
        for provider_name in ordered_providers:
            api_key = available_providers[provider_name]
            if not api_key:
                continue
            try:
                provider_cls = PROVIDER_REGISTRY.get(provider_name.lower())
                if not provider_cls:
                    continue
                provider = provider_cls()
                models = await provider.list_models(api_key)
                for model in models:
                    if preference.requires_vision and not model.supports_vision:
                        continue
                    if preference.requires_tools and not model.supports_tools:
                        continue
                    if preference.requires_streaming and not model.supports_streaming:
                        continue
                    if preference.min_context and model.max_context < preference.min_context:
                        continue
                    score = self._score_model(model, preference, provider_name)
                    candidates.append(ModelCandidate(model_info=model, provider_name=provider_name, score=score))
            except Exception:
                continue
        return candidates

    def _score_model(self, model: ModelInfo, preference: RoutingPreference, provider_name: str) -> float:
        score = 50.0
        if preference.goal == RoutingGoal.CHEAPEST:
            if model.input_price_per_1k is not None:
                score -= model.input_price_per_1k * 10
            if model.latency_tier == "fast":
                score += 5
        elif preference.goal == RoutingGoal.FASTEST:
            if model.latency_tier == "fast":
                score += 30
            elif model.latency_tier == "medium":
                score += 10
            if model.input_price_per_1k is not None:
                score -= model.input_price_per_1k * 2
        elif preference.goal == RoutingGoal.CODING:
            if model.supports_tools:
                score += 20
            if model.quality_tier in ("high", "premium"):
                score += 15
            if provider_name in ("anthropic", "openai"):
                score += 10
        elif preference.goal == RoutingGoal.REASONING:
            if model.quality_tier in ("high", "premium"):
                score += 25
            if model.max_context >= 128000:
                score += 10
        elif preference.goal == RoutingGoal.VISION:
            if model.supports_vision:
                score += 30
            if provider_name in ("openai", "anthropic", "google"):
                score += 10
        elif preference.goal == RoutingGoal.LONG_CONTEXT:
            if model.max_context >= 200000:
                score += 30
            elif model.max_context >= 128000:
                score += 20
            elif model.max_context >= 32000:
                score += 10
        if preference.max_cost_per_1k is not None and model.input_price_per_1k is not None:
            if model.input_price_per_1k > preference.max_cost_per_1k:
                score -= 100
        if provider_name in preference.preferred_providers:
            score += 15
        return score
