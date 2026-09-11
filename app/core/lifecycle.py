"""Application startup and shutdown orchestration.

The API lifespan should be a small composition point.  Service initialization,
cache setup, data seeding, and event-consumer ownership live here so workers
and future entry points can reuse the same policies without importing the
FastAPI application module.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from app.admin.services.feature_seeding import seed_system_feature_flags
from app.core.config import AppSettings
from app.core.database import async_session_factory, init_models
from app.core.logging import configure_logging
from app.services.oauth.seeding import seed_oauth_tool_providers
from app.services.pricing_catalog import seed_pricing_catalog

Broadcast = Callable[[dict], Awaitable[None]]


async def initialize_cache() -> None:
    """Initialize the shared response cache once per API process."""
    from fastapi_cache import FastAPICache
    from fastapi_cache.backends.redis import RedisBackend

    from app.core.redis import redis_client

    FastAPICache.init(RedisBackend(redis_client), prefix="cache")


async def seed_application_data() -> None:
    """Run idempotent catalog/feature seeds using one short-lived session."""
    async with async_session_factory() as db:
        await seed_system_feature_flags(db)
        await seed_oauth_tool_providers(db)
        await seed_pricing_catalog(db)


async def start_application(settings: AppSettings, broadcast: Broadcast) -> asyncio.Task:
    """Validate and start process-owned API resources."""
    settings.validate_startup()
    configure_logging()

    # Alembic is the production schema authority.  This opt-in is retained
    # only for lightweight local development without a migration step.
    if settings.AUTO_CREATE_TABLES:
        if settings.is_production:
            raise RuntimeError("AUTO_CREATE_TABLES cannot be enabled in production")
        await init_models()

    await initialize_cache()
    await seed_application_data()

    from app.core.runtime_events import consume_runtime_events

    return asyncio.create_task(consume_runtime_events(broadcast))


async def stop_application(runtime_event_task: asyncio.Task | None) -> None:
    """Cancel process-owned background resources during graceful shutdown."""
    if runtime_event_task is None:
        return
    runtime_event_task.cancel()
    try:
        await runtime_event_task
    except asyncio.CancelledError:
        pass
