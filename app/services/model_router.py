from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.services.model_providers import PROVIDER_REGISTRY
from app.services.model_providers.base import ModelInfo, ProviderResponse
from app.services.model_registry import list_registered_models, model_info_for
from app.services.provider_health import FailoverManager, failover_manager
from app.services.token_engine import CompletionUsage, TokenEngine


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
    required_context_tokens: int | None = None
    requires_vision: bool = False
    requires_tools: bool = False
    requires_streaming: bool = False
    failover_enabled: bool = True


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
        self._latency_tracker: dict[str, list[float]] = {}
        self.last_invoked_candidate: ModelCandidate | None = None
        self.last_usage: CompletionUsage | None = None
        self.last_routing_reason: str | None = None
        self.last_attempts: list[dict[str, Any]] = []
        # Routing chooses the best candidate; failover decides which eligible
        # candidates may be attempted after a provider error.
        self.failover = FailoverManager(failover_manager.health)

    async def route(self, preference: RoutingPreference, available_providers: dict[str, str]) -> ModelCandidate | None:
        candidates = await self._build_candidates(preference, available_providers)
        if not candidates:
            return None
        candidates = [c for c in candidates if c.available]
        if not candidates:
            return None
        candidates.sort(key=lambda c: c.score, reverse=True)
        self.last_routing_reason = self._routing_reason(preference, candidates[0])
        return candidates[0]

    async def route_with_fallback(self, preference: RoutingPreference, available_providers: dict[str, str]) -> list[ModelCandidate]:
        candidates = await self._build_candidates(preference, available_providers)
        if not candidates:
            return []
        candidates = [c for c in candidates if c.available]
        candidates.sort(key=lambda c: c.score, reverse=True)
        if candidates:
            self.last_routing_reason = self._routing_reason(preference, candidates[0])
        if preference.failover_enabled:
            return candidates
        return candidates[:1]

    async def _invoke_with_fallback(
        self,
        preference: RoutingPreference,
        available_providers: dict[str, str],
        messages: list[dict[str, str]],
        max_tokens: int = 2048,
        temperature: float = 0.7,
        on_token: Callable[[str], Awaitable[None]] | None = None,
    ) -> tuple[str | None, str, str, str]:
        self.last_invoked_candidate = None
        self.last_usage = None
        self.last_attempts = []
        candidates = await self.route_with_fallback(preference, available_providers)
        candidates = await self.failover.eligible_async(candidates)
        if not candidates:
            return None, "", "", "No healthy provider is currently available for this request"
        last_error = ""
        for candidate in candidates:
            streamed_any = False
            stream_usage: dict[str, Any] = {}

            async def capture_usage(
                payload: dict[str, Any],
                usage_sink: dict[str, Any] = stream_usage,
            ) -> None:
                # Streaming APIs may send input and output usage in separate
                # frames. Keep both instead of replacing the earlier frame.
                usage_sink.update(payload)
            attempt: dict[str, Any] = {
                "provider": candidate.provider_name,
                "model": candidate.model_info.id,
                "status": "started",
            }
            self.last_attempts.append(attempt)
            try:
                provider_cls = PROVIDER_REGISTRY.get(candidate.provider_name.lower())
                if not provider_cls:
                    continue
                provider = provider_cls()
                start = time.perf_counter()
                candidate_output_tokens = min(
                    max_tokens,
                    candidate.model_info.max_output_tokens or max_tokens,
                )
                if on_token is None:
                    result = await provider.chat_completion(
                        api_key=available_providers[candidate.provider_name],
                        model=candidate.model_info.id,
                        messages=messages,
                        max_tokens=candidate_output_tokens,
                        temperature=temperature,
                    )
                else:
                    chunks: list[str] = []
                    async for chunk in provider.chat_completion_stream(
                        api_key=available_providers[candidate.provider_name],
                        model=candidate.model_info.id,
                        messages=messages,
                        max_tokens=candidate_output_tokens,
                        temperature=temperature,
                        on_usage=capture_usage,
                    ):
                        text_chunk = str(chunk)
                        if not text_chunk:
                            continue
                        chunks.append(text_chunk)
                        streamed_any = True
                        await on_token(text_chunk)
                    result = ProviderResponse("".join(chunks), stream_usage)
                latency = (time.perf_counter() - start) * 1000
                self.record_latency(candidate.provider_name, candidate.model_info.id, latency)
                await self.failover.succeeded_async(candidate, latency)
                self.last_invoked_candidate = candidate
                text, usage = TokenEngine.normalize_usage(
                    result,
                    estimated_input_tokens=TokenEngine.estimate_messages(messages),
                    estimated_output_tokens=TokenEngine.estimate_text(
                        str(result if isinstance(result, str) else "")
                    ),
                )
                self.last_usage = usage
                attempt.update(
                    {
                        "status": "completed",
                        "latency_ms": round(latency, 2),
                        "usage": usage.as_dict(),
                    }
                )
                return text, candidate.model_info.id, candidate.provider_name, ""
            except Exception as exc:
                last_error = str(exc)
                await self.failover.failed_async(candidate, last_error)
                attempt.update({"status": "failed", "error": last_error[:500]})
                # Retrying after visible output would interleave two answers.
                # Once a stream has started, surface the failure instead of
                # silently switching providers mid-response.
                if streamed_any:
                    return None, "", "", last_error
                continue
        return None, "", "", last_error

    async def invoke_fixed(
        self,
        provider_name: str,
        model_names: list[str],
        available_providers: dict[str, str],
        messages: list[dict[str, str]],
        max_tokens: int = 2048,
        temperature: float = 0.7,
        on_token: Callable[[str], Awaitable[None]] | None = None,
    ) -> tuple[str, str, str, str]:
        """Invoke the runtime's configured provider/model without auto-routing.

        Runtime routing is opt-in. Keeping this path separate from
        ``_invoke_with_fallback`` prevents a runtime configured for one
        provider from silently selecting a different provider just because a
        global API key happens to be present.
        """
        self.last_invoked_candidate = None
        self.last_usage = None
        self.last_attempts = []
        provider_key = provider_name.strip().lower()
        api_key = available_providers.get(provider_key)
        if not api_key:
            return "", "", provider_key, f"No credentials are configured for provider '{provider_key}'"
        provider_cls = PROVIDER_REGISTRY.get(provider_key)
        if not provider_cls:
            return "", "", provider_key, f"Provider '{provider_key}' is not supported"
        last_error = ""
        for model_name in [item.strip() for item in model_names if item and item.strip()]:
            streamed_any = False
            stream_usage: dict[str, Any] = {}

            async def capture_usage(
                payload: dict[str, Any],
                usage_sink: dict[str, Any] = stream_usage,
            ) -> None:
                usage_sink.update(payload)
            attempt: dict[str, Any] = {
                "provider": provider_key,
                "model": model_name,
                "status": "started",
            }
            self.last_attempts.append(attempt)
            try:
                provider = provider_cls()
                start = time.perf_counter()
                configured_info = model_info_for(provider_key, model_name)
                output_limit = min(
                    max_tokens,
                    configured_info.max_output_tokens or max_tokens,
                )
                if on_token is None:
                    result = await provider.chat_completion(
                        api_key=api_key,
                        model=model_name,
                        messages=messages,
                        max_tokens=output_limit,
                        temperature=temperature,
                    )
                else:
                    chunks: list[str] = []
                    async for chunk in provider.chat_completion_stream(
                        api_key=api_key,
                        model=model_name,
                        messages=messages,
                        max_tokens=output_limit,
                        temperature=temperature,
                        on_usage=capture_usage,
                    ):
                        text_chunk = str(chunk)
                        if not text_chunk:
                            continue
                        chunks.append(text_chunk)
                        streamed_any = True
                        await on_token(text_chunk)
                    result = ProviderResponse("".join(chunks), stream_usage)
                latency = (time.perf_counter() - start) * 1000
                self.record_latency(provider_key, model_name, latency)
                await self.failover.health.record_success_async(provider_key, latency)
                self.last_invoked_candidate = ModelCandidate(
                    model_info=model_info_for(provider_key, model_name),
                    provider_name=provider_key,
                )
                text, usage = TokenEngine.normalize_usage(
                    result,
                    estimated_input_tokens=TokenEngine.estimate_messages(messages),
                    estimated_output_tokens=TokenEngine.estimate_text(
                        str(result if isinstance(result, str) else "")
                    ),
                )
                self.last_usage = usage
                attempt.update(
                    {
                        "status": "completed",
                        "latency_ms": round(latency, 2),
                        "usage": usage.as_dict(),
                    }
                )
                self.last_routing_reason = f"Configured {provider_key}/{model_name}"
                return text, model_name, provider_key, ""
            except Exception as exc:
                last_error = str(exc)
                await self.failover.health.record_failure_async(provider_key, last_error)
                attempt.update({"status": "failed", "error": last_error[:500]})
                if streamed_any:
                    return "", "", provider_key, last_error
        return "", "", provider_key, last_error or "No configured model was available"

    async def _build_candidates(self, preference: RoutingPreference, available_providers: dict[str, str]) -> list[ModelCandidate]:
        candidates: list[ModelCandidate] = []
        provider_priority = self.PROVIDER_PRIORITY.get(preference.goal, self.PROVIDER_PRIORITY[RoutingGoal.BALANCED])
        prioritized = [
            p for p in provider_priority
            if p in available_providers and p not in preference.excluded_providers
        ]
        # A balanced route must not silently ignore a connected provider that
        # is not in the goal's preferred list (for example Google or Mistral).
        # Keep the goal order first, then consider every remaining provider.
        ordered_providers = prioritized + sorted(
            p for p in available_providers
            if p not in prioritized and p not in preference.excluded_providers
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
                # Provider model discovery can be unavailable or rate limited.
                # Keep automatic routing useful by falling back to Zyntry's
                # public capability registry while credentials are present.
                if not models:
                    models = [item.as_model_info() for item in list_registered_models(provider_name)]
                for model in models:
                    if preference.requires_vision and not model.supports_vision:
                        continue
                    if preference.requires_tools and not model.supports_tools:
                        continue
                    if preference.requires_streaming and not model.supports_streaming:
                        continue
                    required_context = preference.required_context_tokens or preference.min_context
                    if required_context and model.max_context < required_context:
                        continue
                    score = self._score_model(model, preference, provider_name)
                    candidates.append(ModelCandidate(model_info=model, provider_name=provider_name, score=score))
            except Exception as exc:
                await self.failover.health.record_failure_async(provider_name, str(exc))
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

    @staticmethod
    def _routing_reason(preference: RoutingPreference, candidate: ModelCandidate) -> str:
        requirements: list[str] = [f"goal={preference.goal.value}"]
        required_context = preference.required_context_tokens or preference.min_context
        if required_context:
            requirements.append(f"context>={required_context}")
        if preference.requires_tools:
            requirements.append("tool calling")
        if preference.requires_vision:
            requirements.append("vision")
        if preference.preferred_providers:
            requirements.append("preferred provider")
        return f"Selected {candidate.provider_name}/{candidate.model_info.id} ({', '.join(requirements)})"

    def record_latency(self, provider: str, model: str, latency_ms: float) -> None:
        key = f"{provider}:{model}"
        self._latency_tracker.setdefault(key, []).append(latency_ms)
        if len(self._latency_tracker[key]) > 100:
            self._latency_tracker[key] = self._latency_tracker[key][-100:]

    def get_avg_latency(self, provider: str, model: str) -> float | None:
        key = f"{provider}:{model}"
        vals = self._latency_tracker.get(key, [])
        if not vals:
            return None
        return sum(vals) / len(vals)
