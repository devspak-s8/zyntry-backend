import httpx

from app.services.model_providers.base import BaseModelProvider, ModelInfo


class BedrockProvider(BaseModelProvider):
    BASE_URL = "https://bedrock-runtime.us-east-1.amazonaws.com"

    def name(self) -> str:
        return "bedrock"

    def display_name(self) -> str:
        return "Amazon Bedrock"

    async def list_models(self, api_key: str) -> list[ModelInfo]:
        models: list[ModelInfo] = []
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{self.BASE_URL}/v1/models",
                headers={"x-amzn-bedrock-api-key": api_key},
            )
            if resp.status_code != 200:
                return models
            data = resp.json()
            for m in data.get("modelSummaries", []):
                model_id = m.get("modelId", "")
                models.append(ModelInfo(
                    id=model_id,
                    name=model_id,
                    provider=self.display_name(),
                    max_context=self._get_context(model_id),
                    supports_vision=self._supports_vision(model_id),
                    supports_tools=self._supports_tools(model_id),
                    supports_streaming=True,
                    latency_tier=self._get_latency_tier(model_id),
                    quality_tier=self._get_quality_tier(model_id),
                ))
        return models

    async def test_connection(self, api_key: str) -> bool:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{self.BASE_URL}/v1/models",
                headers={"x-amzn-bedrock-api-key": api_key},
            )
            return resp.status_code == 200

    def _get_context(self, model_id: str) -> int:
        if "claude" in model_id.lower():
            return 200000
        if "llama" in model_id.lower():
            return 16384
        return 128000

    def _supports_vision(self, model_id: str) -> bool:
        return "claude" in model_id.lower()

    def _supports_tools(self, model_id: str) -> bool:
        return "claude" in model_id.lower() or "llama" in model_id.lower()

    def _get_latency_tier(self, model_id: str) -> str:
        if "haiku" in model_id.lower():
            return "low"
        if "sonnet" in model_id.lower():
            return "medium"
        return "high"

    def _get_quality_tier(self, model_id: str) -> str:
        if "opus" in model_id.lower():
            return "premium"
        if "sonnet" in model_id.lower():
            return "high"
        return "standard"