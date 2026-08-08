import httpx

from app.services.model_providers.base import BaseModelProvider, ModelInfo


class GoogleProvider(BaseModelProvider):
    BASE_URL = "https://generativelanguage.googleapis.com/v1"

    def name(self) -> str:
        return "google"

    def display_name(self) -> str:
        return "Google"

    async def list_models(self, api_key: str) -> list[ModelInfo]:
        models: list[ModelInfo] = []
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{self.BASE_URL}/models?key={api_key}",
            )
            if resp.status_code != 200:
                return models
            data = resp.json()
            for m in data.get("models", []):
                model_id = m.get("name", "").replace("models/", "")
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
                f"{self.BASE_URL}/models?key={api_key}",
            )
            return resp.status_code == 200

    async def chat_completion(self, api_key: str, model: str, messages: list[dict[str, str]], max_tokens: int = 2048, temperature: float = 0.7) -> str:
        contents = []
        for msg in messages:
            role = "user" if msg["role"] == "user" else "model"
            contents.append({"role": role, "parts": [{"text": msg["content"]}]})
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{self.BASE_URL}/models/{model}:generateContent?key={api_key}",
                headers={"Content-Type": "application/json"},
                json={"contents": contents, "generationConfig": {"maxOutputTokens": max_tokens, "temperature": temperature}},
            )
            resp.raise_for_status()
            data = resp.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]

    def _get_context(self, model_id: str) -> int:
        if "2.5-pro" in model_id.lower():
            return 1000000
        if "2.5-flash" in model_id.lower():
            return 1000000
        if "1.5-pro" in model_id.lower():
            return 2000000
        if "1.5-flash" in model_id.lower():
            return 1000000
        return 1000000

    def _supports_vision(self, model_id: str) -> bool:
        return True

    def _supports_tools(self, model_id: str) -> bool:
        return True

    def _get_latency_tier(self, model_id: str) -> str:
        if "flash" in model_id.lower():
            return "low"
        return "medium"

    def _get_quality_tier(self, model_id: str) -> str:
        if "pro" in model_id.lower():
            return "premium"
        return "high"

    def _get_input_price(self, model_id: str) -> float | None:
        if "2.5-pro" in model_id.lower():
            return 0.0025
        if "2.5-flash" in model_id.lower():
            return 0.0001
        if "1.5-pro" in model_id.lower():
            return 0.002
        if "1.5-flash" in model_id.lower():
            return 0.0001
        return None

    def _get_output_price(self, model_id: str) -> float | None:
        if "2.5-pro" in model_id.lower():
            return 0.01
        if "2.5-flash" in model_id.lower():
            return 0.0004
        if "1.5-pro" in model_id.lower():
            return 0.006
        if "1.5-flash" in model_id.lower():
            return 0.0004
        return None