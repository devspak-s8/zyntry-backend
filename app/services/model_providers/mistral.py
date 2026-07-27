import httpx

from app.services.model_providers.base import BaseModelProvider, ModelInfo


class MistralProvider(BaseModelProvider):
    BASE_URL = "https://api.mistral.ai/v1"

    def name(self) -> str:
        return "mistral"

    def display_name(self) -> str:
        return "Mistral"

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
                    supports_tools=True,
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
        if "large" in model_id.lower():
            return 128000
        return 32768

    def _supports_vision(self, model_id: str) -> bool:
        return "vision" in model_id.lower() or "pixtral" in model_id.lower()

    def _get_latency_tier(self, model_id: str) -> str:
        if "small" in model_id.lower():
            return "low"
        return "medium"

    def _get_quality_tier(self, model_id: str) -> str:
        if "large" in model_id.lower():
            return "high"
        return "standard"

    def _get_input_price(self, model_id: str) -> float | None:
        if "large" in model_id.lower():
            return 0.002
        if "medium" in model_id.lower():
            return 0.0001
        if "small" in model_id.lower():
            return 0.00003
        return None

    def _get_output_price(self, model_id: str) -> float | None:
        if "large" in model_id.lower():
            return 0.006
        if "medium" in model_id.lower():
            return 0.0003
        if "small" in model_id.lower():
            return 0.0001
        return None