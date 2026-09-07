"""Normalized model metadata used by routing and context budgeting.

Provider discovery is useful when a customer connects a provider, but it is
not available for every request (and provider APIs can be slow or unavailable).
This small registry supplies safe, versioned defaults for the models Zyntry
supports.  Live provider metadata can still take precedence at routing time.

Credentials are deliberately not stored here.  The registry contains public
capability and pricing metadata only.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import Any

from app.services.model_providers.base import ModelInfo


@dataclass(frozen=True, slots=True)
class RegisteredModel:
    id: str
    provider: str
    context_window: int
    max_output_tokens: int
    input_price_per_1k: float | None = None
    output_price_per_1k: float | None = None
    supports_reasoning: bool = False
    supports_vision: bool = False
    supports_tools: bool = False
    supports_streaming: bool = True
    supports_structured_output: bool = False
    supports_embeddings: bool = False
    latency_tier: str = "medium"
    quality_tier: str = "standard"
    metadata_version: str = "2026-09-01"

    @property
    def max_context(self) -> int:
        """Compatibility alias used by ``ModelInfo`` and the router."""

        return self.context_window

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["max_context"] = data.pop("context_window")
        return data

    def as_model_info(self) -> ModelInfo:
        return ModelInfo(
            id=self.id,
            name=self.id,
            provider=self.provider,
            max_context=self.context_window,
            supports_vision=self.supports_vision,
            supports_tools=self.supports_tools,
            supports_streaming=self.supports_streaming,
            input_price_per_1k=self.input_price_per_1k,
            output_price_per_1k=self.output_price_per_1k,
            latency_tier=self.latency_tier,
            quality_tier=self.quality_tier,
            supports_reasoning=self.supports_reasoning,
            supports_structured_output=self.supports_structured_output,
            supports_embeddings=self.supports_embeddings,
            max_output_tokens=self.max_output_tokens,
            config={"metadata_version": self.metadata_version},
        )


# Values are conservative defaults.  They are intentionally kept separate
# from provider credentials and may be updated independently as providers
# publish new limits and prices.
_MODELS: tuple[RegisteredModel, ...] = (
    RegisteredModel("gpt-4o", "openai", 128_000, 16_384, 0.005, 0.015, True, True, True, True, True, False, "medium", "high"),
    RegisteredModel("gpt-4o-mini", "openai", 128_000, 16_384, 0.00015, 0.0006, False, True, True, True, True, False, "low", "standard"),
    RegisteredModel("gpt-4.1", "openai", 1_000_000, 32_768, 0.003, 0.012, True, True, True, True, True, False, "medium", "premium"),
    RegisteredModel("gpt-4.1-mini", "openai", 1_000_000, 32_768, 0.0003, 0.0012, True, True, True, True, True, False, "low", "high"),
    RegisteredModel("gpt-3.5-turbo", "openai", 16_385, 4_096, 0.0005, 0.0015, False, False, True, True, False, False, "low", "standard"),
    RegisteredModel("gemini-2.5-flash", "google", 1_000_000, 65_536, 0.0001, 0.0004, True, True, True, True, True, False, "low", "high"),
    RegisteredModel("gemini-2.5-pro", "google", 1_000_000, 65_536, 0.0025, 0.01, True, True, True, True, True, False, "medium", "premium"),
    RegisteredModel("gemini-1.5-flash", "google", 1_000_000, 8_192, 0.0001, 0.0004, False, True, True, True, True, False, "low", "high"),
    RegisteredModel("gemini-1.5-pro", "google", 2_000_000, 8_192, 0.002, 0.006, True, True, True, True, True, False, "medium", "premium"),
    RegisteredModel("claude-3-5-sonnet-latest", "anthropic", 200_000, 8_192, 0.003, 0.015, True, True, True, True, True, False, "medium", "premium"),
    RegisteredModel("claude-3-5-haiku-latest", "anthropic", 200_000, 8_192, 0.0008, 0.004, False, True, True, True, True, False, "low", "high"),
    RegisteredModel("deepseek-chat", "deepseek", 128_000, 8_192, 0.00014, 0.00028, False, False, True, True, True, False, "low", "high"),
    RegisteredModel("deepseek-reasoner", "deepseek", 128_000, 8_192, 0.00055, 0.00219, True, False, True, True, True, False, "medium", "premium"),
    RegisteredModel("mistral-large-latest", "mistral", 128_000, 8_192, 0.002, 0.006, True, False, True, True, True, False, "medium", "high"),
    RegisteredModel("llama-3.3-70b-versatile", "groq", 128_000, 32_768, 0.00059, 0.00079, False, False, True, True, True, False, "low", "high"),
)

_BY_ID = {(item.provider, item.id.lower()): item for item in _MODELS}


@lru_cache(maxsize=64)
def _cached_registered_models(provider: str | None = None) -> tuple[RegisteredModel, ...]:
    """Cache immutable registry slices; callers still receive a fresh list."""

    return tuple(item for item in _MODELS if provider is None or item.provider == provider)


def list_registered_models(provider: str | None = None) -> list[RegisteredModel]:
    """Return public registry metadata, optionally filtered by provider.

    Registry metadata is static/semi-static and read on every routing request,
    so cache the immutable slice in-process.  A Redis-backed cache can replace
    this implementation when model metadata becomes tenant-configurable.
    """

    normalized = provider.strip().lower() if provider else None
    return list(_cached_registered_models(normalized))


def get_registered_model(provider: str | None, model: str | None) -> RegisteredModel | None:
    """Resolve an exact or family model identifier from the registry."""

    if not model:
        return None
    normalized_model = model.strip().lower()
    normalized_provider = provider.strip().lower() if provider else None
    if normalized_provider:
        exact = _BY_ID.get((normalized_provider, normalized_model))
        if exact:
            return exact
    for item in _cached_registered_models():
        if normalized_provider and item.provider != normalized_provider:
            continue
        if normalized_model == item.id.lower() or normalized_model.startswith(item.id.lower() + "-"):
            return item
    # Aggregators expose upstream model IDs (for example ``openrouter/*``).
    # Use the upstream family when it is recognizable, while preserving the
    # requested provider for telemetry.
    for item in _cached_registered_models():
        if normalized_model == item.id.lower() or item.id.lower() in normalized_model:
            return RegisteredModel(
                id=model,
                provider=normalized_provider or item.provider,
                context_window=item.context_window,
                max_output_tokens=item.max_output_tokens,
                input_price_per_1k=item.input_price_per_1k,
                output_price_per_1k=item.output_price_per_1k,
                supports_reasoning=item.supports_reasoning,
                supports_vision=item.supports_vision,
                supports_tools=item.supports_tools,
                supports_streaming=item.supports_streaming,
                supports_structured_output=item.supports_structured_output,
                supports_embeddings=item.supports_embeddings,
                latency_tier=item.latency_tier,
                quality_tier=item.quality_tier,
                metadata_version=item.metadata_version,
            )
    return None


def model_info_for(provider: str | None, model: str | None, *, fallback_context: int = 128_000) -> ModelInfo:
    """Return normalized metadata, including safe values for custom models."""

    registered = get_registered_model(provider, model)
    if registered:
        return registered.as_model_info()
    return ModelInfo(
        id=model or "unknown",
        name=model or "unknown",
        provider=(provider or "unknown").strip().lower(),
        max_context=max(1, fallback_context),
        supports_vision=False,
        supports_tools=False,
        supports_streaming=True,
        max_output_tokens=min(8_192, max(1_024, fallback_context // 8)),
        config={"metadata_version": "conservative-default"},
    )


class ModelRegistry:
    """Small service facade for dependency injection and future persistence."""

    def list(self, provider: str | None = None) -> list[RegisteredModel]:
        return list_registered_models(provider)

    def resolve(self, provider: str | None, model: str | None) -> RegisteredModel | None:
        return get_registered_model(provider, model)

    def info(self, provider: str | None, model: str | None) -> ModelInfo:
        return model_info_for(provider, model)


model_registry = ModelRegistry()
