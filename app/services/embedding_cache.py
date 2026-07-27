from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.embedding_cache import EmbeddingCache
from app.repositories.embedding_cache import EmbeddingCacheRepository


class EmbeddingCacheService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = EmbeddingCacheRepository(session)

    async def get(
        self,
        project_id: UUID,
        content_hash: str,
        embedding_version: str,
        embedding_model: str,
        provider: str,
    ) -> list[float] | None:
        entry = await self.repo.find_active(
            project_id=project_id,
            content_hash=content_hash,
            embedding_version=embedding_version,
            embedding_model=embedding_model,
            provider=provider,
        )
        if entry is None:
            return None
        return list(entry.vector)

    async def set(
        self,
        project_id: UUID,
        content_hash: str,
        embedding_version: str,
        embedding_model: str,
        provider: str,
        vector: list[float],
        dimensions: int,
        metadata: dict | None = None,
        ttl_days: int = 30,
    ) -> None:
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=ttl_days) if ttl_days > 0 else None
        entry = EmbeddingCache(
            project_id=project_id,
            content_hash=content_hash,
            embedding_version=embedding_version,
            embedding_model=embedding_model,
            provider=provider,
            dimensions=dimensions,
            vector=vector,
            meta=metadata or {},
            expires_at=expires_at,
        )
        await self.repo.upsert(entry)

    async def delete_expired(self) -> int:
        return await self.repo.delete_expired()

    async def get_or_generate(
        self,
        project_id: UUID,
        content_hash: str,
        embedding_version: str,
        embedding_model: str,
        provider: str,
        generator_coroutine,
        metadata: dict | None = None,
    ) -> list[float]:
        cached = await self.get(
            project_id=project_id,
            content_hash=content_hash,
            embedding_version=embedding_version,
            embedding_model=embedding_model,
            provider=provider,
        )
        if cached is not None:
            return cached
        result = await generator_coroutine()
        await self.set(
            project_id=project_id,
            content_hash=content_hash,
            embedding_version=embedding_version,
            embedding_model=embedding_model,
            provider=provider,
            vector=result,
            dimensions=len(result),
            metadata=metadata,
        )
        return result
