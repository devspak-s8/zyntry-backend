from __future__ import annotations

import asyncio
import hashlib
import random
import string
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_session
from app.models.knowledge import Document
from app.models.runtimes import Runtime, RuntimeBuildChunk
from app.repositories import UnitOfWork
from app.services.chunking import chunk_documents
from app.services.embeddings import (
    EmbeddingMetadata,
    compute_content_hash,
    embed_with_cache,
    get_embedding_provider,
)
from app.services.vector_stores import get_vector_store


RUNTIME_STAGES = [
    "collect_sources",
    "validate_sources",
    "discover_resources",
    "extract_documents",
    "normalize_documents",
    "clean_documents",
    "chunk_documents",
    "generate_embeddings",
    "store_embeddings",
    "build_runtime",
    "generate_api_key",
    "activate_runtime",
]


class RuntimeWorker:
    def __init__(self, runtime_id: str, trigger: str = "manual") -> None:
        self.runtime_id = runtime_id
        self.trigger = trigger
        self._session: AsyncSession | None = None
        self._uow: UnitOfWork | None = None
        self._runtime: Runtime | None = None
        self._vector_store: Any = None
        self._embedding_provider: Any = None
        self._generated_embeddings: dict[str, list[float]] = {}
        self._cache_service: Any = None

    async def _ensure_session(self) -> tuple[AsyncSession, UnitOfWork]:
        if self._session is None:
            session_gen = get_session()
            self._session = await session_gen.__anext__()
            self._uow = UnitOfWork(self._session)
        return self._session, self._uow  # type: ignore[return-value]

    async def _ensure_cache_service(self) -> Any:
        if self._cache_service is None:
            from app.services.embedding_cache import EmbeddingCacheService
            self._cache_service = EmbeddingCacheService(self._session)  # type: ignore[arg-type]
        return self._cache_service

    async def _get_documents(self) -> list[Document]:
        if not self._runtime or not self._uow:
            return []
        kbs = await self._uow.knowledge_bases.get_by_project(self._runtime.project_id)
        docs: list[Document] = []
        for kb in kbs:
            docs.extend(await self._uow.documents.get_by_kb(kb.id))
        return docs

    async def run(self) -> None:
        session, uow = await self._ensure_session()
        try:
            self._runtime = await uow.runtimes.get(uuid.UUID(self.runtime_id))
            if not self._runtime:
                return
            await uow.runtime_build_chunks.delete_by_runtime(uuid.UUID(self.runtime_id))
            await uow.runtime_build_logs.delete_by_runtime(uuid.UUID(self.runtime_id))
            await uow.session.commit()
            from app.main import manager
            await manager.broadcast({"type": "RuntimeStarted", "runtime_id": str(self._runtime.id)})
            for stage in RUNTIME_STAGES:
                if self._runtime.status == "cancelled":
                    break
                await self._run_stage(stage)
            if self._runtime.status != "cancelled" and self._runtime.status != "failed":
                self._runtime.status = "active"
                self._runtime.health = 100.0
                await uow.runtimes.update(self._runtime, status="active", health=100.0)
                await uow.session.commit()
                from app.main import manager
                await manager.broadcast({"type": "RuntimeReady", "runtime_id": str(self._runtime.id)})
        except Exception as e:
            if self._runtime:
                await uow.runtimes.update(self._runtime, status="failed", error_message=str(e))
                await uow.session.commit()
                from app.main import manager
                await manager.broadcast({"type": "RuntimeFailed", "runtime_id": str(self._runtime.id), "error": str(e)})
            raise
        finally:
            if self._embedding_provider:
                await self._embedding_provider.close()

    async def _run_stage(self, stage: str) -> None:
        if not self._runtime or not self._uow:
            return
        start_time = datetime.now(UTC)
        log = await self._uow.runtime_build_logs.create(
            runtime_id=self._runtime.id,
            stage=stage,
            status="started",
            started_at=start_time,
            metadata_={"trigger": self.trigger},
        )
        await self._uow.session.commit()
        from app.main import manager
        await manager.broadcast({"type": _stage_event(stage), "runtime_id": str(self._runtime.id), "stage": stage})
        stage_method = getattr(self, f"_stage_{stage}", None)
        if stage_method:
            try:
                await stage_method()
                log.status = "completed"
                log.completed_at = datetime.now(UTC)
                await self._uow.runtime_build_logs.update(log, status="completed", completed_at=datetime.now(UTC))
            except Exception as e:
                log.status = "failed"
                log.error_message = str(e)
                log.completed_at = datetime.now(UTC)
                await self._uow.runtime_build_logs.update(
                    log, status="failed", error_message=str(e), completed_at=datetime.now(UTC)
                )
                self._runtime.status = "failed"
                self._runtime.error_message = str(e)
                await uow.runtimes.update(self._runtime, status="failed", error_message=str(e))
                raise
        else:
            await asyncio.sleep(random.uniform(0.1, 0.5))
            log.status = "completed"
            log.completed_at = datetime.now(UTC)
            await self._uow.runtime_build_logs.update(log, status="completed", completed_at=datetime.now(UTC))
        await self._uow.session.commit()

    async def _stage_collect_sources(self) -> None:
        self._runtime.status = "validating"
        await self._update_runtime_status("validating")

    async def _stage_validate_sources(self) -> None:
        sources = await self._uow.knowledge_sources.get_by_project(self._runtime.project_id)
        for source in sources:
            if not source.is_active:
                continue
        self._runtime.status = "discovering"
        await self._update_runtime_status("discovering")

    async def _stage_discover_resources(self) -> None:
        self._runtime.status = "extracting"
        await self._update_runtime_status("extracting")

    async def _stage_extract_documents(self) -> None:
        docs = await self._get_documents()
        for doc in docs:
            content_hash = compute_content_hash(doc.content or "")
            existing = await self._uow.runtime_build_chunks.get_by_document(self._runtime.id, doc.id)
            if existing and existing[0].embedding_hash == content_hash:
                continue
        self._runtime.status = "cleaning"
        await self._update_runtime_status("cleaning")

    async def _stage_normalize_documents(self) -> None:
        self._runtime.status = "chunking"
        await self._update_runtime_status("chunking")

    async def _stage_clean_documents(self) -> None:
        pass

    async def _stage_chunk_documents(self) -> None:
        docs = await self._get_documents()
        if not docs:
            self._runtime.documents = 0
            await self._update_runtime_counts(documents=0, chunks=0)
            return

        doc_dicts = []
        for doc in docs:
            doc_dicts.append({
                "id": str(doc.id),
                "content": doc.content or "",
                "source": doc.source,
                "strategy": "auto",
            })

        chunks = chunk_documents(
            doc_dicts,
            chunk_size=self._runtime.chunk_size,
            overlap=self._runtime.chunk_overlap,
        )

        chunks_to_create = []
        for chunk in chunks:
            chunks_to_create.append({
                "runtime_id": self._runtime.id,
                "document_id": uuid.UUID(chunk.document_id) if chunk.document_id else None,
                "chunk_index": chunk.chunk_index,
                "action": "new",
                "embedded": False,
                "indexed": False,
                "embedding_hash": chunk.hash,
                "metadata_": {
                    "text_length": len(chunk.content),
                    "section": chunk.section,
                    "heading": chunk.heading,
                    "page": chunk.page,
                    "source": chunk.source,
                    "language": chunk.language,
                    "version": chunk.version,
                    "strategy": chunk.metadata.get("strategy", "auto"),
                    "token_count": chunk.metadata.get("token_count", 0),
                    "content": chunk.content,
                },
            })

        if chunks_to_create:
            await self._uow.runtime_build_chunks.bulk_create(chunks_to_create)
            self._runtime.chunks = len(chunks_to_create)
        self._runtime.documents = len(docs)
        await self._update_runtime_counts(documents=len(docs), chunks=len(chunks_to_create))

    async def _stage_generate_embeddings(self) -> None:
        provider_name = self._runtime.embedding_model.split("/")[0] if "/" in self._runtime.embedding_model else "openai"
        self._embedding_provider = get_embedding_provider(
            provider_name=provider_name,
            api_key=getattr(settings, f"{provider_name.upper()}_API_KEY", ""),
            model=self._runtime.embedding_model,
        )
        cache_service = await self._ensure_cache_service()
        chunks = await self._uow.runtime_build_chunks.get_by_runtime(self._runtime.id)
        docs = await self._get_documents()
        doc_map = {str(d.id): d for d in docs}
        texts = []
        metadatas = []
        chunk_map: dict[int, RuntimeBuildChunk] = {}
        for chunk in chunks:
            if chunk.embedded:
                continue
            doc = doc_map.get(str(chunk.document_id)) if chunk.document_id else None
            if not doc or not doc.content:
                continue
            text = (chunk.metadata_ or {}).get("content") or doc.content[:self._runtime.chunk_size]
            texts.append(text)
            metadatas.append(EmbeddingMetadata(
                document_id=str(chunk.document_id) if chunk.document_id else "",
                chunk_id=str(chunk.id),
                source=doc.source or "",
                content_hash=chunk.embedding_hash or "",
            ))
            chunk_map[len(texts) - 1] = chunk
        if texts:
            batch_size = getattr(settings, "EMBEDDING_BATCH_SIZE", 100)
            max_concurrency = getattr(settings, "EMBEDDING_MAX_CONCURRENCY", 4)
            embeddings = await embed_with_cache(
                provider=self._embedding_provider,
                texts=texts,
                metadata=metadatas,
                project_id=self._runtime.project_id,
                cache_service=cache_service,
                use_cache=True,
                batch_size=batch_size,
                max_concurrency=max_concurrency,
            )
            for idx, embedding in enumerate(embeddings):
                chunk = chunk_map[idx]
                chunk.embedded = True
                self._generated_embeddings[str(chunk.id)] = embedding
                await self._uow.runtime_build_chunks.update(chunk, embedded=True)
        self._runtime.status = "indexing"
        await self._update_runtime_status("indexing")
        self._runtime.embeddings = sum(1 for c in chunks if c.embedded)
        await self._update_runtime_counts(embeddings=self._runtime.embeddings)

    async def _stage_store_embeddings(self) -> None:
        self._vector_store = get_vector_store(
            provider=self._runtime.vector_store,
            session=self._uow.session,  # type: ignore[arg-type]
            table_name="embeddings",
        )
        chunks = await self._uow.runtime_build_chunks.get_by_runtime(self._runtime.id)
        docs = await self._get_documents()
        doc_map = {str(d.id): d for d in docs}
        vectors = []
        for chunk in chunks:
            if not chunk.embedded or chunk.indexed:
                continue
            embedding = self._generated_embeddings.get(str(chunk.id))
            if not embedding:
                continue
            doc = doc_map.get(str(chunk.document_id)) if chunk.document_id else None
            vectors.append({
                "id": str(chunk.id),
                "project_id": str(self._runtime.project_id),
                "document_id": str(chunk.document_id) if chunk.document_id else None,
                "vector": embedding,
                "model": self._runtime.embedding_model,
                "dimensions": len(embedding),
                "metadata": {
                    "document_id": str(chunk.document_id) if chunk.document_id else "",
                    "chunk_id": str(chunk.id),
                    "source": doc.source if doc and doc.source else "",
                    "content_hash": chunk.embedding_hash or "",
                    "embedding_version": "1",
                },
                "external_id": str(chunk.id),
            })
            chunk.indexed = True
            await self._uow.runtime_build_chunks.update(chunk, indexed=True)
        if vectors:
            batch_size = getattr(settings, "VECTOR_BATCH_SIZE", 100)
            if hasattr(self._vector_store, "bulk_upsert"):
                await self._vector_store.bulk_upsert(vectors, batch_size=batch_size)
            else:
                await self._vector_store.upsert(vectors)
        self._runtime.index_size = len(vectors)
        await self._update_runtime_counts(index_size=len(vectors))
        self._runtime.status = "building"
        await self._update_runtime_status("building")

    async def _stage_build_runtime(self) -> None:
        self._runtime.status = "provisioning"
        await self._update_runtime_status("provisioning")

    async def _stage_generate_api_key(self) -> None:
        raw_key = "zyntra_" + "".join(random.choices(string.ascii_letters + string.digits, k=32))
        hashed_key = hashlib.sha256(raw_key.encode()).hexdigest()
        api_key = await self._uow.api_keys.create(
            name=f"Runtime API Key - {self._runtime.project_id}",
            hashed_key=hashed_key,
            prefix=raw_key[:12],
            organization_id=self._runtime.organization_id,
            project_id=self._runtime.project_id,
        )
        await self._uow.commit()
        self._runtime.api_key_id = api_key.id
        await self._uow.runtimes.update(self._runtime, api_key_id=api_key.id)
        self._runtime.config["api_key"] = raw_key
        await self._uow.runtimes.update(self._runtime, config=self._runtime.config)

    async def _stage_activate_runtime(self) -> None:
        self._runtime.last_build_completed = datetime.now(UTC)
        await self._uow.runtimes.update(self._runtime, last_build_completed=datetime.now(UTC))
        await self._uow.commit()

    async def _update_runtime_status(self, status: str) -> None:
        if not self._runtime:
            return
        self._runtime.status = status
        await self._uow.runtimes.update(self._runtime, status=status)
        await self._uow.session.commit()

    async def _update_runtime_counts(self, **kwargs: int) -> None:
        if not self._runtime:
            return
        for key, value in kwargs.items():
            setattr(self._runtime, key, value)
        await self._uow.runtimes.update(self._runtime, **kwargs)
        await self._uow.session.commit()


def _stage_event(stage: str) -> str:
    mapping = {
        "collect_sources": "ValidationStarted",
        "validate_sources": "DiscoveryStarted",
        "discover_resources": "ExtractionStarted",
        "extract_documents": "CleaningStarted",
        "normalize_documents": "ChunkingStarted",
        "clean_documents": "ChunkingStarted",
        "chunk_documents": "EmbeddingStarted",
        "generate_embeddings": "IndexingStarted",
        "store_embeddings": "IndexingStarted",
        "build_runtime": "ProvisioningStarted",
        "generate_api_key": "ProvisioningStarted",
        "activate_runtime": "RuntimeReady",
    }
    return mapping.get(stage, "RuntimeStarted")