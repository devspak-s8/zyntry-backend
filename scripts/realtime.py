#!/usr/bin/env python3
"""Standalone Realtime Service.

Runs independently from the FastAPI process and handles WebSocket broadcasting,
runtime events, build progress, notifications, live logs, runtime hot reload,
streaming responses, and future SSE support via Redis Pub/Sub.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import redis.asyncio as redis
from app.core.config import settings
from app.core.logging import configure_logging

configure_logging()
logger = logging.getLogger(__name__)

CHANNELS = [
    "zyntra:events",
    "zyntra:notifications",
    "zyntra:runtime",
    "zyntra:builds",
    "zyntra:logs",
    "zyntra:hotreload",
]


class RealtimeService:
    def __init__(self, redis_client: redis.Redis) -> None:
        self.redis = redis_client
        self._running = False

    async def start(self) -> None:
        self._running = True
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(*CHANNELS)

        logger.info("Realtime Service started, listening for events...")

        async for message in pubsub.listen():
            if not self._running:
                break
            if message["type"] == "message":
                await self._handle_event(message)

    async def stop(self) -> None:
        self._running = False
        await self.redis.close()

    async def _handle_event(self, message: dict[str, Any]) -> None:
        try:
            data = json.loads(message["data"])
            channel = message["channel"]
            logger.debug(f"Received event on {channel}: {data}")
            await self._broadcast(channel, data)
        except (json.JSONDecodeError, Exception) as exc:
            logger.error(f"Failed to handle event: {exc}")

    async def _broadcast(self, channel: str, data: dict[str, Any]) -> None:
        event = {
            "channel": channel,
            "data": data,
            "timestamp": data.get("timestamp"),
        }
        await self.redis.publish("zyntra:broadcast", json.dumps(event))


async def main() -> None:
    redis_client = redis.from_url(
        settings.redis_url,
        decode_responses=True,
    )
    await redis_client.ping()
    logger.info("Connected to Redis")

    service = RealtimeService(redis_client)

    try:
        await service.start()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await service.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Realtime Service stopped")
