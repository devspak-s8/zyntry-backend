from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from app.services.embedding_cache import EmbeddingCacheService


@pytest.mark.asyncio
async def test_set_creates_timezone_aware_cache_expiry() -> None:
    service = EmbeddingCacheService(AsyncMock())
    service.repo.upsert = AsyncMock()

    await service.set(
        project_id=uuid.uuid4(),
        content_hash="content-hash",
        embedding_version="1",
        embedding_model="text-embedding-3-small",
        provider="openai",
        vector=[0.1, 0.2],
        dimensions=2,
    )

    entry = service.repo.upsert.await_args.args[0]
    assert entry.expires_at is not None
    assert entry.expires_at.tzinfo is not None
