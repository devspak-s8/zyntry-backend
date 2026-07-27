import httpx

from app.services.model_providers.base import BaseModelProvider, ModelInfo


class GroqProvider(BaseModelProvider):
    BASE_URL = "https://api.groq.com/openai/v1"

    def name(self) -> str:
        return "groq"

    def display_name(self) -> str:
        return "Groq"

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
                    supports_vision=False,
                    supports_tools=True,
                    supports_streaming=True,
                    input_price_per_1k=self._get_input_price(model_id),
                    output_price_per_1k=self._get_output_price(model_id),
                    latency_tier="low",
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
        if "llama-3.3" in model_id.lower() or "llama-3" in model_id.lower():
            return 128000
        if "mixtral" in model_id.lower():
            return 32768
        return 128000

    def _supports_tools(self, model_id: str) -> bool:
        return True

    def _get_quality_tier(self, model_id: str) -> str:
        if "llama-3.3" in model_id.lower() or "llama-3.1" in model_id.lower():
            return "high"
        return "standard"

    def _get_input_price(self, model_id: str) -> float | None:
        if "llama-3.3" in model_id.lower():
            return 0.00059
        if "mixtral" in model_id.lower():
            return 0.00024
        return None

    def _get_output_price(self, model_id: str) -> float | None:
        if "llama-3.3" in model_id.lower():
            return 0.00079
        if "mixtral" in model_id.lower():
            return 0.00024
        return None