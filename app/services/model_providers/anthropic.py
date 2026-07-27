import httpx

from app.services.model_providers.base import BaseModelProvider, ModelInfo


class AnthropicProvider(BaseModelProvider):
    BASE_URL = "https://api.anthropic.com/v1"

    def name(self) -> str:
        return "anthropic"

    def display_name(self) -> str:
        return "Anthropic"

    async def list_models(self, api_key: str) -> list[ModelInfo]:
        models: list[ModelInfo] = []
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{self.BASE_URL}/models",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                },
            )
            if resp.status_code != 200:
                return models
            data = resp.json()
            for m in data.get("data", []):
                model_id = m.get("id", "")
                models.append(ModelInfo(
                    id=model_id,
                    name=model_id,
                    provider=self.display_name(),
                    max_context=self._get_context(model_id),
                    supports_vision=self._supports_vision(model_id),
                    supports_tools=self._supports_tools(model_id),
                    supports_streaming=True,
                    input_price_per_1k=self._get_input_price(model_id),
                    output_price_per_1k=self._get_output_price(model_id),
                    latency_tier=self._get_latency_tier(model_id),
                    quality_tier=self._get_quality_tier(model_id),
                ))
        return models

    async def test_connection(self, api_key: str) -> bool:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{self.BASE_URL}/models",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                },
            )
            return resp.status_code == 200

    def _get_context(self, model_id: str) -> int:
        if "opus" in model_id.lower():
            return 200000
        if "sonnet" in model_id.lower():
            return 200000
        if "haiku" in model_id.lower():
            return 200000
        return 200000

    def _supports_vision(self, model_id: str) -> bool:
        return "claude-3" in model_id.lower() or "claude-4" in model_id.lower()

    def _supports_tools(self, model_id: str) -> bool:
        return "claude-3" in model_id.lower() or "claude-4" in model_id.lower()

    def _get_latency_tier(self, model_id: str) -> str:
        if "haiku" in model_id.lower():
            return "low"
        if "sonnet" in model_id.lower():
            return "medium"
        return "high"

    def _get_quality_tier(self, model_id: str) -> str:
        if "haiku" in model_id.lower():
            return "standard"
        if "sonnet" in model_id.lower():
            return "high"
        return "premium"

    def _get_input_price(self, model_id: str) -> float | None:
        if "opus" in model_id.lower():
            return 0.015
        if "sonnet" in model_id.lower():
            return 0.003
        if "haiku" in model_id.lower():
            return 0.00025
        return None

    def _get_output_price(self, model_id: str) -> float | None:
        if "opus" in model_id.lower():
            return 0.075
        if "sonnet" in model_id.lower():
            return 0.015
        if "haiku" in model_id.lower():
            return 0.00125
        return None