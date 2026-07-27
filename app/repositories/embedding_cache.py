from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.embedding_cache import EmbeddingCache


class EmbeddingCacheRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def find_active(
        self,
        project_id: UUID,
        content_hash: str,
        embedding_version: str,
        embedding_model: str,
        provider: str,
    ) -> EmbeddingCache | None:
        now = datetime.now(timezone.utc)
        result = await self.session.execute(
            select(EmbeddingCache).where(
                EmbeddingCache.project_id == project_id,
                EmbeddingCache.content_hash == content_hash,
                EmbeddingCache.embedding_version == embedding_version,
                EmbeddingCache.embedding_model == embedding_model,
                EmbeddingCache.provider == provider,
                (EmbeddingCache.expires_at.is_(None) | (EmbeddingCache.expires_at > now)),
            )
        )
        return result.scalar_one_or_none()

    async def upsert(self, cache_entry: EmbeddingCache) -> EmbeddingCache:
        existing = await self.session.execute(
            select(EmbeddingCache).where(
                EmbeddingCache.project_id == cache_entry.project_id,
                EmbeddingCache.content_hash == cache_entry.content_hash,
                EmbeddingCache.embedding_version == cache_entry.embedding_version,
                EmbeddingCache.embedding_model == cache_entry.embedding_model,
                EmbeddingCache.provider == cache_entry.provider,
            )
        )
        entry = existing.scalar_one_or_none()
        if entry:
            entry.dimensions = cache_entry.dimensions
            entry.vector = cache_entry.vector
            entry.meta = cache_entry.meta
            entry.expires_at = cache_entry.expires_at
            await self.session.flush()
            return entry
        self.session.add(cache_entry)
        await self.session.flush()
        return cache_entry

    async def delete_expired(self) -> int:
        now = datetime.now(timezone.utc)
        result = await self.session.execute(
            select(EmbeddingCache).where(
                EmbeddingCache.expires_at.is_not(None),
                EmbeddingCache.expires_at <= now,
            )
        )
        expired = list(result.scalars().all())
        for entry in expired:
            await self.session.delete(entry)
        await self.session.flush()
        return len(expired)
