from __future__ import annotations

import os
from typing import Any

from app.core.config import settings
from app.services.model_providers import PROVIDER_REGISTRY
from app.services.model_providers.base import ModelInfo


class ModelDiscoveryService:
    def __init__(self) -> None:
        self._cache: dict[str, Any] | None = None
        self._cache_ttl: int = 300

    async def discover_all_models(self) -> list[dict]:
        results: list[dict] = []
        for provider_name, provider_class in PROVIDER_REGISTRY.items():
            api_key = self._get_api_key(provider_name)
            if not api_key:
                results.append({
                    "name": provider_name,
                    "display_name": provider_class().display_name(),
                    "connected": False,
                    "models": [],
                    "model_count": 0,
                })
                continue
            try:
                provider = provider_class()
                models = await provider.list_models(api_key)
                results.append({
                    "name": provider_name,
                    "display_name": provider.display_name(),
                    "connected": True,
                    "models": [self._model_to_dict(m) for m in models],
                    "model_count": len(models),
                })
            except Exception:
                results.append({
                    "name": provider_name,
                    "display_name": provider_class().display_name(),
                    "connected": False,
                    "models": [],
                    "model_count": 0,
                })
        return results

    async def get_models_by_provider(self, provider_name: str) -> list[ModelInfo]:
        provider_class = PROVIDER_REGISTRY.get(provider_name)
        if not provider_class:
            return []
        api_key = self._get_api_key(provider_name)
        if not api_key:
            return []
        provider = provider_class()
        return await provider.list_models(api_key)

    async def refresh_models(self) -> list[dict]:
        self._cache = None
        return await self.discover_all_models()

    def _get_api_key(self, provider_name: str) -> str | None:
        key_map = {
            "openai": settings.OPENAI_API_KEY,
            "anthropic": settings.ANTHROPIC_API_KEY,
            "google": settings.GOOGLE_API_KEY,
            "deepseek": settings.DEEPSEEK_API_KEY,
            "groq": settings.GROQ_API_KEY,
            "openrouter": settings.OPENROUTER_API_KEY,
            "mistral": settings.MISTRAL_API_KEY,
            "meta": "",
            "bedrock": settings.AWS_ACCESS_KEY_ID,
        }
        return key_map.get(provider_name)

    def _model_to_dict(self, model: ModelInfo) -> dict:
        return {
            "id": model.id,
            "name": model.name,
            "provider": model.provider,
            "max_context": model.max_context,
            "supports_vision": model.supports_vision,
            "supports_tools": model.supports_tools,
            "supports_streaming": model.supports_streaming,
            "input_price_per_1k": model.input_price_per_1k,
            "output_price_per_1k": model.output_price_per_1k,
            "latency_tier": model.latency_tier,
            "quality_tier": model.quality_tier,
            "config": model.config,
        }


_model_discovery = ModelDiscoveryService()


def get_model_discovery() -> ModelDiscoveryService:
    return _model_discovery