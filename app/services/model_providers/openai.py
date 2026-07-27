import httpx

from app.services.model_providers.base import BaseModelProvider, ModelInfo


class OpenAIProvider(BaseModelProvider):
    BASE_URL = "https://api.openai.com/v1"

    def name(self) -> str:
        return "openai"

    def display_name(self) -> str:
        return "OpenAI"

    async def list_models(self, api_key: str) -> list[ModelInfo]:
        models: list[ModelInfo] = []
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{self.BASE_URL}/models",
                headers={"Authorization": f"Bearer {api_key}"},
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
                headers={"Authorization": f"Bearer {api_key}"},
            )
            return resp.status_code == 200

    def _get_context(self, model_id: str) -> int:
        contexts = {
            "gpt-4o": 128000, "gpt-4o-mini": 128000,
            "gpt-4-turbo": 128000, "gpt-4": 8192,
            "gpt-3.5-turbo": 4096, "gpt-4o-audio-preview": 128000,
            "gpt-4.1": 1000000, "gpt-4.1-mini": 1000000,
            "gpt-4.1-nano": 1000000,
        }
        for key, val in contexts.items():
            if key in model_id.lower():
                return val
        return 128000

    def _supports_vision(self, model_id: str) -> bool:
        vision_models = {"gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-4.1", "gpt-4.1-mini", "gpt-4.1-nano"}
        return any(m in model_id.lower() for m in vision_models)

    def _supports_tools(self, model_id: str) -> bool:
        return "gpt-4" in model_id.lower() or "gpt-3" not in model_id.lower()

    def _get_latency_tier(self, model_id: str) -> str:
        if "mini" in model_id.lower() or "nano" in model_id.lower():
            return "low"
        if "4o" in model_id.lower() or "4.1-mini" in model_id.lower():
            return "medium"
        return "high"

    def _get_quality_tier(self, model_id: str) -> str:
        if "mini" in model_id.lower() or "nano" in model_id.lower():
            return "standard"
        if "4.1" in model_id.lower():
            return "premium"
        return "high"

    def _get_input_price(self, model_id: str) -> float | None:
        prices = {"gpt-4o-mini": 0.00015, "gpt-4o": 0.005, "gpt-4-turbo": 0.01, "gpt-4": 0.03, "gpt-4.1": 0.003, "gpt-4.1-mini": 0.0003, "gpt-4.1-nano": 0.00015}
        for key, val in prices.items():
            if key in model_id.lower():
                return val
        return None

    def _get_output_price(self, model_id: str) -> float | None:
        prices = {"gpt-4o-mini": 0.0006, "gpt-4o": 0.015, "gpt-4-turbo": 0.03, "gpt-4": 0.06, "gpt-4.1": 0.012, "gpt-4.1-mini": 0.0012, "gpt-4.1-nano": 0.0006}
        for key, val in prices.items():
            if key in model_id.lower():
                return val
        return None