from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

UsageCallback = Callable[[dict[str, Any]], Awaitable[None] | None]


async def emit_usage(callback: UsageCallback | None, usage: Any) -> None:
    """Forward provider usage without making adapters care about sync/async callbacks."""
    if not callback or not isinstance(usage, dict) or not usage:
        return
    result = callback(usage)
    if result is not None:
        await result


class ProviderResponse(str):
    """Text-compatible provider response carrying optional usage metadata."""

    usage: dict[str, Any]
    content: str

    def __new__(cls, content: str, usage: dict[str, Any] | None = None) -> "ProviderResponse":
        value = super().__new__(cls, content)
        value.usage = usage or {}
        value.content = content
        return value


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
    # Appended after the original fields to preserve positional construction
    # compatibility for existing provider adapters.
    max_output_tokens: int = 8192
    supports_reasoning: bool = False
    supports_structured_output: bool = False
    supports_embeddings: bool = False


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

    async def chat_completion_stream(
        self,
        api_key: str,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int = 2048,
        temperature: float = 0.7,
        on_usage: UsageCallback | None = None,
    ) -> AsyncGenerator[str]:
        """Yield response chunks, with a safe one-chunk fallback.

        Providers that expose native SSE override this method.  Keeping a
        compatibility fallback means a provider can still participate in the
        invoke stream while its adapter is upgraded.
        """

        result = await self.chat_completion(
            api_key=api_key,
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        await emit_usage(on_usage, getattr(result, "usage", None))
        yield str(result)

    def get_provider_key(self) -> str:
        return self.name()
