from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

from app.core.redis import redis_client


RUNTIME_EVENT_CHANNEL = "zyntry:runtime-events"


async def publish_runtime_event(event: dict[str, Any]) -> None:
    await redis_client.publish(RUNTIME_EVENT_CHANNEL, json.dumps(event))


async def consume_runtime_events(
    handler: Callable[[dict[str, Any]], Awaitable[None]],
) -> None:
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(RUNTIME_EVENT_CHANNEL)
    try:
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message and message.get("data"):
                try:
                    event = json.loads(message["data"])
                    if isinstance(event, dict):
                        await handler(event)
                except (json.JSONDecodeError, TypeError):
                    pass
            await asyncio.sleep(0.05)
    finally:
        await pubsub.unsubscribe(RUNTIME_EVENT_CHANNEL)
        await pubsub.aclose()
