from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, TypeVar

import httpx

T = TypeVar("T")
R = TypeVar("R")


class ConnectionPool:
    def __init__(
        self,
        limit: int = 100,
        limit_per_host: int = 30,
        max_keepalive_connections: int = 20,
        keepalive_expiry: float = 5.0,
        timeout: float = 30.0,
    ) -> None:
        self._limit = limit
        self._limit_per_host = limit_per_host
        self._max_keepalive = max_keepalive_connections
        self._keepalive_expiry = keepalive_expiry
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            limits = httpx.Limits(
                max_connections=self._limit,
                max_keepalive_connections=self._max_keepalive,
                keepalive_expiry=self._keepalive_expiry,
            )
            self._client = httpx.AsyncClient(
                limits=limits,
                timeout=self._timeout,
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> ConnectionPool:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        await self.close()


class BatchProcessor:
    def __init__(self, batch_size: int = 100) -> None:
        self.batch_size = batch_size

    def split_into_batches(self, items: list[T]) -> list[list[T]]:
        if not items:
            return []
        return [items[i : i + self.batch_size] for i in range(0, len(items), self.batch_size)]

    @staticmethod
    async def process_batches(
        batches: list[list[T]],
        processor_fn: Callable[[list[T]], R],
        max_concurrency: int = 10,
    ) -> list[R]:
        semaphore = asyncio.Semaphore(max_concurrency)

        async def _process_batch(batch: list[T]) -> R:
            async with semaphore:
                return await processor_fn(batch)

        tasks = [_process_batch(batch) for batch in batches]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        processed: list[R] = []
        for result in results:
            if isinstance(result, Exception):
                raise result
            processed.append(result)

        return processed


class EmbeddingBatcher:
    def __init__(
        self,
        provider: Any,
        project_id: Any,
        cache_service: Any,
        batch_size: int = 100,
        max_concurrency: int = 4,
        use_cache: bool = True,
    ) -> None:
        self._provider = provider
        self._project_id = project_id
        self._cache_service = cache_service
        self._batch_size = batch_size
        self._max_concurrency = max_concurrency
        self._use_cache = use_cache

    async def batch_embed(
        self,
        texts: list[str],
        metadatas: list[Any],
    ) -> list[list[float]]:
        if not texts:
            return []

        if len(texts) <= self._batch_size:
            from app.services.embeddings import embed_with_cache
            return await embed_with_cache(
                provider=self._provider,
                texts=texts,
                metadata=metadatas,
                project_id=self._project_id,
                cache_service=self._cache_service,
                use_cache=self._use_cache,
            )

        batches = self._split_into_batches(texts, metadatas)
        results = await BatchProcessor.process_batches(
            batches,
            lambda pair: embed_with_cache(
                provider=self._provider,
                texts=pair[0],
                metadata=pair[1],
                project_id=self._project_id,
                cache_service=self._cache_service,
                use_cache=self._use_cache,
            ),
            max_concurrency=self._max_concurrency,
        )

        combined: list[list[float]] = []
        for result in results:
            combined.extend(result)

        return combined

    def _split_into_batches(
        self,
        texts: list[str],
        metadatas: list[Any],
    ) -> list[tuple[list[str], list[Any]]]:
        pairs = list(zip(texts, metadatas, strict=True))
        batches: list[tuple[list[str], list[Any]]] = []
        for i in range(0, len(pairs), self._batch_size):
            batch_pairs = pairs[i : i + self._batch_size]
            batch_texts = [p[0] for p in batch_pairs]
            batch_metas = [p[1] for p in batch_pairs]
            batches.append((batch_texts, batch_metas))
        return batches


async def batch_embed(
    provider: Any,
    texts: list[str],
    metadatas: list[Any],
    project_id: Any,
    cache_service: Any,
    batch_size: int = 100,
    use_cache: bool = True,
    max_concurrency: int = 4,
) -> list[list[float]]:
    if not texts:
        return []

    if len(texts) <= batch_size:
        from app.services.embeddings import embed_with_cache
        return await embed_with_cache(
            provider=provider,
            texts=texts,
            metadata=metadatas,
            project_id=project_id,
            cache_service=cache_service,
            use_cache=use_cache,
        )

    batcher = EmbeddingBatcher(
        provider=provider,
        project_id=project_id,
        cache_service=cache_service,
        batch_size=batch_size,
        max_concurrency=max_concurrency,
        use_cache=use_cache,
    )
    return await batcher.batch_embed(texts, metadatas)


async def parallel_process(  # noqa: UP047
    items: list[T],
    processor_fn: Callable[[T], R],
    max_concurrency: int = 10,
) -> list[R]:
    semaphore = asyncio.Semaphore(max_concurrency)

    async def _process(item: T) -> R:
        async with semaphore:
            return await processor_fn(item)

    tasks = [_process(item) for item in items]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    processed: list[R] = []
    for result in results:
        if isinstance(result, Exception):
            raise result
        processed.append(result)

    return processed


async def bulk_upsert_vectors(
    vector_store: Any,
    vectors: list[dict[str, Any]],
    batch_size: int = 100,
) -> None:
    if not vectors:
        return

    if hasattr(vector_store, "bulk_upsert"):
        await vector_store.bulk_upsert(vectors, batch_size=batch_size)
        return

    batches = [vectors[i : i + batch_size] for i in range(0, len(vectors), batch_size)]
    await asyncio.gather(
        *[vector_store.upsert(batch) for batch in batches],
        return_exceptions=True,
    )