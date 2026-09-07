"""Provider-neutral token estimation and usage normalization."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(slots=True)
class CompletionUsage:
    input_tokens: int
    output_tokens: int
    cached_tokens: int = 0
    source: str = "estimated"

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["total_tokens"] = self.total_tokens
        return data


class TokenEngine:
    """Conservative token accounting shared by routing, billing and analytics.

    Provider tokenizers differ and are not all available in the API process.
    The estimator therefore uses a documented character heuristic for
    preflight.  Provider-reported usage always wins after execution.
    """

    CHARS_PER_TOKEN = 4
    MESSAGE_OVERHEAD = 4

    @classmethod
    def estimate_text(cls, text: str | None) -> int:
        if not text:
            return 0
        return max(1, (len(text) + cls.CHARS_PER_TOKEN - 1) // cls.CHARS_PER_TOKEN)

    @classmethod
    def estimate_messages(cls, messages: Iterable[dict[str, Any]]) -> int:
        total = 0
        for message in messages:
            content = message.get("content", "") if isinstance(message, dict) else str(message)
            total += cls.estimate_text(str(content)) + cls.MESSAGE_OVERHEAD
        return total

    @classmethod
    def normalize_usage(
        cls,
        result: Any,
        *,
        estimated_input_tokens: int,
        estimated_output_tokens: int,
    ) -> tuple[str, CompletionUsage]:
        """Extract usage from provider result without breaking string providers.

        Providers currently return plain text, while integrations and future
        adapters may return a response object, a ``(text, usage)`` tuple, or a
        dictionary containing OpenAI/Gemini/Anthropic usage fields.
        """

        text = result
        usage_payload: Any = None
        if isinstance(result, tuple) and len(result) >= 2:
            text, usage_payload = result[0], result[1]
        elif isinstance(result, dict):
            text = result.get("text") or result.get("content") or result.get("response") or ""
            usage_payload = result.get("usage") or result.get("usageMetadata") or result
        elif hasattr(result, "usage"):
            usage_payload = getattr(result, "usage", None)
            text = getattr(result, "text", None) or getattr(result, "content", None) or str(result)

        input_tokens = cls._read_int(usage_payload, "input_tokens", "prompt_tokens", "promptTokenCount")
        output_tokens = cls._read_int(usage_payload, "output_tokens", "completion_tokens", "candidatesTokenCount")
        cached_tokens = cls._read_int(usage_payload, "cached_tokens", "cachedTokenCount")
        total_tokens = cls._read_int(usage_payload, "total_tokens", "totalTokenCount")
        if isinstance(usage_payload, (int, float)):
            total_tokens = max(0, int(usage_payload))
        if total_tokens and not (input_tokens or output_tokens):
            input_tokens = min(estimated_input_tokens, total_tokens)
            output_tokens = max(0, total_tokens - input_tokens)
        declared_source = ""
        if isinstance(usage_payload, dict):
            declared_source = str(usage_payload.get("source") or "").strip().lower()
        if declared_source in {"estimated", "provider", "mixed"}:
            source = declared_source
        else:
            source = "provider" if input_tokens or output_tokens or total_tokens else "estimated"
        usage = CompletionUsage(
            input_tokens=input_tokens or estimated_input_tokens,
            output_tokens=output_tokens or estimated_output_tokens,
            cached_tokens=cached_tokens,
            source=source,
        )
        return str(text or ""), usage

    @classmethod
    def aggregate(cls, usages: Iterable[CompletionUsage]) -> CompletionUsage:
        """Aggregate usage across model calls in one runtime execution."""

        items = list(usages)
        if not items:
            return CompletionUsage(0, 0, source="estimated")
        sources = {item.source for item in items}
        source = next(iter(sources)) if len(sources) == 1 else "mixed"
        return CompletionUsage(
            input_tokens=sum(max(0, item.input_tokens) for item in items),
            output_tokens=sum(max(0, item.output_tokens) for item in items),
            cached_tokens=sum(max(0, item.cached_tokens) for item in items),
            source=source,
        )

    @staticmethod
    def _read_int(payload: Any, *keys: str) -> int:
        if payload is None:
            return 0
        if hasattr(payload, "model_dump"):
            payload = payload.model_dump()
        if not isinstance(payload, dict):
            return 0
        for key in keys:
            value = payload.get(key)
            if isinstance(value, dict):
                value = value.get("total") or value.get("count")
            try:
                if value is not None:
                    return max(0, int(value))
            except (TypeError, ValueError):
                continue
        return 0
