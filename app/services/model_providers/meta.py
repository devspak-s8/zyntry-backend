import httpx

from app.services.model_providers.base import BaseModelProvider, ModelInfo


class MetaProvider(BaseModelProvider):
    BASE_URL = "https://api.llama-api.com/v1"

    def name(self) -> str:
        return "meta"

    def display_name(self) -> str:
        return "Meta"

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

    async def chat_completion(self, api_key: str, model: str, messages: list[dict[str, str]], max_tokens: int = 2048, temperature: float = 0.7) -> str:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{self.BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature},
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    def _get_context(self, model_id: str) -> int:
        if "405b" in model_id.lower():
            return 16384
        return 128000

    def _get_latency_tier(self, model_id: str) -> str:
        if "405b" in model_id.lower():
            return "medium"
        return "low"

    def _get_quality_tier(self, model_id: str) -> str:
        if "405b" in model_id.lower():
            return "high"
        return "standard"

    def _get_input_price(self, model_id: str) -> float | None:
        if "405b" in model_id.lower():
            return 0.002
        return 0.0007

    def _get_output_price(self, model_id: str) -> float | None:
        if "405b" in model_id.lower():
            return 0.002
        return 0.0008