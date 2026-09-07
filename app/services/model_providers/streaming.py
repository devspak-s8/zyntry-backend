"""Shared SSE adapter for OpenAI-compatible provider APIs."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any

import httpx

from app.services.model_providers.base import UsageCallback, emit_usage


async def stream_openai_compatible(
    *,
    url: str,
    headers: dict[str, str],
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    temperature: float,
    on_usage: UsageCallback | None = None,
) -> AsyncGenerator[str]:
    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream(
            "POST",
            url,
            headers=headers,
            json={
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "stream": True,
                # OpenAI-compatible providers that support usage reporting
                # emit a final usage-only SSE frame when this is enabled.
                "stream_options": {"include_usage": True},
            },
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:].strip()
                if payload == "[DONE]":
                    break
                try:
                    data: dict[str, Any] = json.loads(payload)
                    await emit_usage(on_usage, data.get("usage"))
                    choices = data.get("choices") or []
                    delta = choices[0].get("delta", {}) if choices else {}
                    content = delta.get("content")
                    if content:
                        yield str(content)
                except (ValueError, KeyError, IndexError, TypeError):
                    continue
