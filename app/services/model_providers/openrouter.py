import httpx

from app.services.model_providers.base import BaseModelProvider, ModelInfo


class OpenRouterProvider(BaseModelProvider):
    BASE_URL = "https://openrouter.ai/api/v1"

    def name(self) -> str:
        return "openrouter"

    def display_name(self) -> str:
        return "OpenRouter"

    async def list_models(self, api_key: str) -> list[ModelInfo]:
        models: list[ModelInfo] = []
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{self.BASE_URL}/models",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "HTTP-Referer": "https://zyntra.dev",
                    "X-Title": "Zyntra",
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
                    max_context=m.get("context_length", 128000),
                    supports_vision=m.get("vision", False),
                    supports_tools=m.get("function_calling", True),
                    supports_streaming=True,
                    input_price_per_1k=m.get("pricing", {}).get("prompt"),
                    output_price_per_1k=m.get("pricing", {}).get("completion"),
                    latency_tier=self._get_latency_tier(model_id),
                    quality_tier=self._get_quality_tier(model_id),
                ))
        return models

    async def test_connection(self, api_key: str) -> bool:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{self.BASE_URL}/models",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "HTTP-Referer": "https://zyntra.dev",
                    "X-Title": "Zyntra",
                },
            )
            return resp.status_code == 200

    async def chat_completion(self, api_key: str, model: str, messages: list[dict[str, str]], max_tokens: int = 2048, temperature: float = 0.7) -> str:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{self.BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "HTTP-Referer": "https://zyntra.dev",
                    "X-Title": "Zyntra",
                    "Content-Type": "application/json",
                },
                json={"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature},
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    def _get_latency_tier(self, model_id: str) -> str:
        if "fast" in model_id.lower() or "mini" in model_id.lower():
            return "low"
        return "medium"

    def _get_quality_tier(self, model_id: str) -> str:
        if "opus" in model_id.lower() or "premium" in model_id.lower():
            return "premium"
        if "sonnet" in model_id.lower() or "flash" in model_id.lower():
            return "high"
        return "standard"