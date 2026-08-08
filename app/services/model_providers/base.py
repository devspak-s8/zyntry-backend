from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ModelInfo:
    id: str
    name: str
    provider: str
    max_context: int
    supports_vision: bool
    supports_tools: bool
    supports_streaming: bool
    input_price_per_1k: float | None = None
    output_price_per_1k: float | None = None
    latency_tier: str = "medium"
    quality_tier: str = "standard"
    config: dict[str, Any] = field(default_factory=dict)


class BaseModelProvider(ABC):
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def display_name(self) -> str:
        ...

    @abstractmethod
    async def list_models(self, api_key: str) -> list[ModelInfo]:
        ...

    @abstractmethod
    async def test_connection(self, api_key: str) -> bool:
        ...

    @abstractmethod
    async def chat_completion(self, api_key: str, model: str, messages: list[dict[str, str]], max_tokens: int = 2048, temperature: float = 0.7) -> str:
        ...

    def get_provider_key(self) -> str:
        return self.name()