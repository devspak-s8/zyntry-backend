from __future__ import annotations

import asyncio
import json
import math
from abc import ABC, abstractmethod
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class BaseVectorStore(ABC):
    @abstractmethod
    async def upsert(self, vectors: list[dict[str, Any]]) -> None:
        ...

    @abstractmethod
    async def bulk_upsert(self, vectors: list[dict[str, Any]], batch_size: int = 100) -> None:
        ...

    @abstractmethod
    async def delete(self, ids: list[str]) -> None:
        ...

    @abstractmethod
    async def search(self, query_vector: list[float], limit: int = 10, filters: dict | None = None, query_text: str | None = None) -> list[dict]:
        ...

    @abstractmethod
    async def count(self, filters: dict | None = None) -> int:
        ...


class PgVectorStore(BaseVectorStore):
    def __init__(self, session: AsyncSession, table_name: str = "embeddings") -> None:
        self._session = session
        self._table_name = table_name

    async def upsert(self, vectors: list[dict[str, Any]]) -> None:
        if not vectors:
            return
        for vec in vectors:
            await self._session.execute(
                text(
                    f"""
                    INSERT INTO {self._table_name} (id, project_id, document_id, vector, model, dimensions, metadata, external_id)
                    VALUES (:id, :project_id, :document_id, CAST(:vector AS vector), :model, :dimensions, CAST(:metadata AS jsonb), :external_id)
                    ON CONFLICT (id) DO UPDATE SET
                        vector = EXCLUDED.vector::vector,
                        metadata = EXCLUDED.metadata,
                        model = EXCLUDED.model,
                        dimensions = EXCLUDED.dimensions
                    """
                ),
                {
                    "id": vec["id"],
                    "project_id": vec["project_id"],
                    "document_id": vec.get("document_id"),
                    "vector": str(vec["vector"]),
                    "model": vec.get("model", ""),
                    "dimensions": vec.get("dimensions", len(vec["vector"])),
                    "metadata": json.dumps(vec.get("metadata", {})),
                    "external_id": vec.get("external_id"),
                },
            )

    async def bulk_upsert(self, vectors: list[dict[str, Any]], batch_size: int = 100) -> None:
        if not vectors:
            return
        batches = [vectors[i : i + batch_size] for i in range(0, len(vectors), batch_size)]
        # AsyncSession cannot execute concurrent statements safely. Sequential
        # batches also ensure the original database error is never swallowed.
        for batch in batches:
            await self._upsert_batch(batch)

    async def _upsert_batch(self, vectors: list[dict[str, Any]]) -> None:
        if not vectors:
            return
        await self._session.execute(
            text(
                f"""
                INSERT INTO {self._table_name} (id, project_id, document_id, vector, model, dimensions, metadata, external_id)
                VALUES (:id, :project_id, :document_id, CAST(:vector AS vector), :model, :dimensions, CAST(:metadata AS jsonb), :external_id)
                ON CONFLICT (id) DO UPDATE SET
                    vector = EXCLUDED.vector::vector,
                    metadata = EXCLUDED.metadata,
                    model = EXCLUDED.model,
                    dimensions = EXCLUDED.dimensions
                """
            ),
            [
                {
                    "id": vec["id"],
                    "project_id": vec["project_id"],
                    "document_id": vec.get("document_id"),
                    "vector": str(vec["vector"]),
                    "model": vec.get("model", ""),
                    "dimensions": vec.get("dimensions", len(vec["vector"])),
                    "metadata": json.dumps(vec.get("metadata", {})),
                    "external_id": vec.get("external_id"),
                }
                for vec in vectors
            ],
        )

    async def delete(self, ids: list[str]) -> None:
        if not ids:
            return
        await self._session.execute(
            text(f"DELETE FROM {self._table_name} WHERE id = ANY(:ids)"),
            {"ids": ids},
        )

    async def search(self, query_vector: list[float], limit: int = 10, filters: dict | None = None, query_text: str | None = None) -> list[dict]:
        filter_clause = ""
        params: dict[str, Any] = {"query": str(query_vector), "limit": limit}
        if filters:
            conditions = []
            if "project_id" in filters:
                conditions.append("project_id = :project_id")
                params["project_id"] = filters["project_id"]
            if "document_id" in filters:
                conditions.append("document_id = :document_id")
                params["document_id"] = filters["document_id"]
            if conditions:
                filter_clause = "WHERE " + " AND ".join(conditions)

        if query_text:
            ts_query = " & ".join(query_text.split())
            fulltext_clause = f", to_tsvector('english', COALESCE(metadata->>'content', '')) AS content_tsv"
            fulltext_where = f"AND content_tsv @@ to_tsquery('english', :ts_query)"
            sql = text(
                f"""
                SELECT id, project_id, document_id, 1 - (vector <=> CAST(:query AS vector)) AS similarity, metadata
                {fulltext_clause}
                FROM {self._table_name}
                {filter_clause}
                {fulltext_where}
                ORDER BY vector <=> CAST(:query AS vector)
                LIMIT :limit
                """
            )
            params["ts_query"] = ts_query
            result = await self._session.execute(sql, params)
        else:
            result = await self._session.execute(
                text(
                    f"""
                    SELECT id, project_id, document_id, 1 - (vector <=> CAST(:query AS vector)) AS similarity, metadata
                    FROM {self._table_name}
                    {filter_clause}
                    ORDER BY vector <=> CAST(:query AS vector)
                    LIMIT :limit
                    """
                ),
                params,
            )
        rows = result.fetchall()
        return [
            {
                "id": str(row.id),
                "project_id": str(row.project_id) if row.project_id else None,
                "document_id": str(row.document_id) if row.project_id else None,
                "score": float(row.similarity),
                "metadata": row.metadata or {},
            }
            for row in rows
        ]

    async def count(self, filters: dict | None = None) -> int:
        filter_clause = ""
        params: dict[str, Any] = {}
        if filters:
            conditions = []
            if "project_id" in filters:
                conditions.append("project_id = :project_id")
                params["project_id"] = filters["project_id"]
            if conditions:
                filter_clause = "WHERE " + " AND ".join(conditions)
        result = await self._session.execute(
            text(f"SELECT COUNT(*) FROM {self._table_name} {filter_clause}"),
            params,
        )
        row = result.fetchone()
        return row[0] if row else 0


class InMemoryVectorStore(BaseVectorStore):
    def __init__(self) -> None:
        self._vectors: dict[str, dict[str, Any]] = {}

    async def upsert(self, vectors: list[dict[str, Any]]) -> None:
        for vec in vectors:
            self._vectors[vec["id"]] = vec

    async def bulk_upsert(self, vectors: list[dict[str, Any]], batch_size: int = 100) -> None:
        batches = [vectors[i : i + batch_size] for i in range(0, len(vectors), batch_size)]
        await asyncio.gather(
            *[self._upsert_batch(batch) for batch in batches],
            return_exceptions=True,
        )

    async def _upsert_batch(self, vectors: list[dict[str, Any]]) -> None:
        for vec in vectors:
            self._vectors[vec["id"]] = vec

    async def delete(self, ids: list[str]) -> None:
        for id_ in ids:
            self._vectors.pop(id_, None)

    async def search(self, query_vector: list[float], limit: int = 10, filters: dict | None = None, query_text: str | None = None) -> list[dict]:
        def cosine_similarity(a: list[float], b: list[float]) -> float:
            dot = sum(x * y for x, y in zip(a, b))
            mag_a = math.sqrt(sum(x * x for x in a))
            mag_b = math.sqrt(sum(x * x for x in b))
            if mag_a == 0 or mag_b == 0:
                return 0.0
            return dot / (mag_a * mag_b)

        scored = []
        query_lower = (query_text or "").lower()
        for id_, vec in self._vectors.items():
            if filters:
                if "project_id" in filters and str(vec.get("project_id")) != str(filters["project_id"]):
                    continue
                if "document_id" in filters and str(vec.get("document_id")) != str(filters["document_id"]):
                    continue
            score = cosine_similarity(query_vector, vec["vector"])
            meta = vec.get("metadata", {})
            if query_text:
                content = json.dumps(meta).lower()
                if query_lower in content:
                    score += 0.05
            scored.append({
                "id": id_,
                "project_id": str(vec.get("project_id")) if vec.get("project_id") else None,
                "document_id": str(vec.get("document_id")) if vec.get("document_id") else None,
                "score": score,
                "metadata": meta,
            })
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:limit]

    async def count(self, filters: dict | None = None) -> int:
        if not filters:
            return len(self._vectors)
        return sum(
            1 for vec in self._vectors.values()
            if str(vec.get("project_id")) == str(filters.get("project_id"))
        )


def get_vector_store(provider: str, session: AsyncSession | None = None, table_name: str = "embeddings") -> BaseVectorStore:
    if provider == "pgvector":
        if session is None:
            raise ValueError("session is required for pgvector store")
        return PgVectorStore(session=session, table_name=table_name)
    if provider == "memory":
        return InMemoryVectorStore()
    raise ValueError(f"Unsupported vector store provider: {provider}")
