from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

from app.repositories import UnitOfWork
from app.schemas.knowledge import (
    DocumentCreate,
    KnowledgeBaseCreate,
    KnowledgeSourceCreate,
    KnowledgeSourceUpdate,
)
from app.services.chunking import chunk_document
from app.services.connectors import registry
from app.services.document_processor import build_metadata, extract_text
from app.services.encryption import decrypt_value, encrypt_value


class KnowledgeService:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def list_knowledge_bases(self, project_id: str) -> list[dict]:
        kbs = await self.uow.knowledge_bases.get_by_project(project_id)
        return [
            {
                "id": str(kb.id),
                "name": kb.name,
                "description": kb.description,
                "project_id": str(kb.project_id),
                "config": kb.config,
                "document_count": 0,
                "created_at": kb.created_at.isoformat() if kb.created_at else None,
            }
            for kb in kbs
        ]

    async def create_knowledge_base(self, data: KnowledgeBaseCreate) -> dict:
        kb = await self.uow.knowledge_bases.create(
            name=data.name,
            description=data.description,
            project_id=data.project_id,
            config=data.config,
        )
        await self.uow.commit()
        return {
            "id": str(kb.id),
            "name": kb.name,
            "description": kb.description,
            "project_id": str(kb.project_id),
            "config": kb.config,
        }

    async def upload_document(self, data: DocumentCreate) -> dict:
        content = data.content
        if isinstance(content, str):
            content = content.replace("\x00", "")
        doc = await self.uow.documents.create(
            title=data.title,
            content=content,
            source=data.source,
            knowledge_base_id=data.knowledge_base_id,
        )
        await self.uow.commit()
        kb = await self.uow.knowledge_bases.get(uuid.UUID(data.knowledge_base_id))
        project_id = str(kb.project_id) if kb else None
        if project_id:
            await self._maybe_trigger_runtime(
                project_id, trigger="document_uploaded", include_active=True
            )
        return {
            "id": str(doc.id),
            "title": doc.title,
            "source": doc.source,
            "knowledge_base_id": str(doc.knowledge_base_id),
            "chunk_count": doc.chunk_count,
        }

    async def upload_file(
        self,
        content: bytes,
        filename: str,
        content_type: str,
        title: str,
        knowledge_base_id: str,
        source: str | None = None,
    ) -> dict:
        text = extract_text(content, filename, content_type)
        metadata = build_metadata(filename, content_type, len(content))
        doc = await self.uow.documents.create(
            title=title,
            content=text,
            source=source or filename,
            knowledge_base_id=knowledge_base_id,
            doc_metadata=metadata,
        )
        await self.uow.commit()
        kb = await self.uow.knowledge_bases.get(uuid.UUID(knowledge_base_id))
        project_id = str(kb.project_id) if kb else None
        if project_id:
            await self._maybe_trigger_runtime(
                project_id, trigger="document_uploaded", include_active=True
            )
        return {
            "id": str(doc.id),
            "title": doc.title,
            "source": doc.source,
            "knowledge_base_id": str(doc.knowledge_base_id),
            "chunk_count": doc.chunk_count,
            "metadata": metadata,
        }

    async def list_documents(self, knowledge_base_id: str) -> list[dict]:
        docs = await self.uow.documents.get_by_kb(knowledge_base_id)
        return [
            {
                "id": str(d.id),
                "title": d.title,
                "source": d.source,
                "chunk_count": d.chunk_count,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in docs
        ]

    async def list_sources(self, project_id: str) -> list[dict]:
        sources = await self.uow.knowledge_sources.get_by_project(project_id)
        return [
            {
                "id": str(s.id),
                "project_id": str(s.project_id),
                "source_type": s.source_type,
                "display_name": s.display_name,
                "config": s.config,
                "sync_frequency": s.sync_frequency,
                "last_synced_at": s.last_synced_at,
                "status": s.status,
                "is_active": s.is_active,
                "connection_status": s.connection_status,
                "last_error": s.last_error,
                "error_count": s.error_count,
                "sync_progress": s.sync_progress,
                "metadata": s.metadata_,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "updated_at": s.updated_at.isoformat() if s.updated_at else None,
            }
            for s in sources
        ]

    async def create_source(self, data: KnowledgeSourceCreate) -> dict:
        credentials_encrypted = None
        if data.credentials is not None:
            credentials_encrypted = encrypt_value(json.dumps(data.credentials))
        source = await self.uow.knowledge_sources.create(
            project_id=data.project_id,
            source_type=data.source_type,
            display_name=data.display_name,
            config=data.config,
            sync_frequency=data.sync_frequency,
            status="pending",
            connection_status=data.connection_status,
            metadata_=data.metadata,
            credentials_encrypted=credentials_encrypted,
        )
        await self.uow.commit()
        result = {
            "id": str(source.id),
            "project_id": str(source.project_id),
            "source_type": source.source_type,
            "display_name": source.display_name,
            "config": source.config,
            "sync_frequency": source.sync_frequency,
            "last_synced_at": source.last_synced_at,
            "status": source.status,
            "is_active": source.is_active,
            "connection_status": source.connection_status,
            "last_error": source.last_error,
            "error_count": source.error_count,
            "sync_progress": source.sync_progress,
            "metadata": source.metadata_,
        }
        await self._maybe_trigger_runtime(str(source.project_id), trigger="source_created")
        return result

    async def update_source(self, source_id: str, data: KnowledgeSourceUpdate) -> dict:
        source = await self.uow.knowledge_sources.get(source_id)
        if not source:
            raise ValueError("Knowledge source not found")
        update_data = data.model_dump(exclude_unset=True)
        if "metadata" in update_data:
            update_data["metadata_"] = update_data.pop("metadata")
        if "credentials" in update_data:
            if update_data["credentials"] is None:
                update_data["credentials_encrypted"] = None
            else:
                update_data["credentials_encrypted"] = encrypt_value(
                    json.dumps(update_data.pop("credentials"))
                )
        updated = await self.uow.knowledge_sources.update(source, **update_data)
        await self.uow.commit()
        result = {
            "id": str(updated.id),
            "project_id": str(updated.project_id),
            "source_type": updated.source_type,
            "display_name": updated.display_name,
            "config": updated.config,
            "sync_frequency": updated.sync_frequency,
            "last_synced_at": updated.last_synced_at,
            "status": updated.status,
            "is_active": updated.is_active,
            "connection_status": updated.connection_status,
            "last_error": updated.last_error,
            "error_count": updated.error_count,
            "sync_progress": updated.sync_progress,
            "metadata": updated.metadata_,
        }
        await self._maybe_trigger_runtime(str(updated.project_id), trigger="source_updated")
        return result

    async def delete_source(self, source_id: str) -> None:
        source = await self.uow.knowledge_sources.get(source_id)
        if not source:
            raise ValueError("Knowledge source not found")
        project_id = str(source.project_id)
        await self.uow.knowledge_sources.delete(source)
        await self.uow.commit()
        await self._maybe_trigger_runtime(project_id, trigger="source_removed")

    def get_connector(
        self,
        source_type: str,
        project_id: str,
        source_id: str,
        config: dict,
        credentials: dict | None = None,
    ):
        return registry.create(
            name=source_type,
            project_id=project_id,
            source_id=source_id,
            config=config,
            credentials=credentials,
        )

    def _decrypt_credentials(self, source) -> dict | None:
        if not source.credentials_encrypted:
            return None
        try:
            return json.loads(decrypt_value(source.credentials_encrypted))
        except Exception:
            return None

    async def test_source(self, source_id: str) -> dict:
        source = await self.uow.knowledge_sources.get(source_id)
        if not source:
            raise ValueError("Knowledge source not found")
        connector = self.get_connector(
            source_type=source.source_type,
            project_id=str(source.project_id),
            source_id=str(source.id),
            config=source.config,
            credentials=self._decrypt_credentials(source),
        )
        result = await connector.test()
        await self.uow.knowledge_sources.update(
            source,
            connection_status="connected" if result.get("success") else "error",
            last_error=None if result.get("success") else result.get("message"),
        )
        await self.uow.commit()
        return result

    async def discover_source(self, source_id: str) -> dict:
        source = await self.uow.knowledge_sources.get(source_id)
        if not source:
            raise ValueError("Knowledge source not found")
        connector = self.get_connector(
            source_type=source.source_type,
            project_id=str(source.project_id),
            source_id=str(source.id),
            config=source.config,
            credentials=self._decrypt_credentials(source),
        )
        result = await connector.discover()
        await self.uow.knowledge_sources.update(
            source,
            metadata_=result,
        )
        await self.uow.commit()
        return result

    async def sync_source(self, source_id: str, options: dict | None = None) -> dict:
        source = await self.uow.knowledge_sources.get(source_id)
        if not source:
            raise ValueError("Knowledge source not found")
        connector = self.get_connector(
            source_type=source.source_type,
            project_id=str(source.project_id),
            source_id=str(source.id),
            config=source.config,
            credentials=self._decrypt_credentials(source),
        )
        job = await self.uow.sync_jobs.create(
            source_id=source.id,
            project_id=source.project_id,
            status="running",
            progress=0,
            started_at=datetime.now(UTC),
            stats={},
        )
        await self.uow.knowledge_sources.update(
            source,
            status="syncing",
            sync_progress=0,
        )
        await self.uow.commit()

        try:
            sync_result = await connector.sync(options)
            if sync_result.get("status") == "failed":
                raise ValueError(sync_result.get("error") or "Source synchronization failed")

            documents_synced = 0
            if source.source_type in {"website", "crawler"}:
                documents_synced = await self._persist_website_items(
                    source,
                    sync_result.get("items", []),
                )

            completed_at = datetime.now(UTC)
            stats = {
                "items_discovered": sync_result.get("total", 0),
                "documents_synced": documents_synced,
            }
            await self.uow.sync_jobs.update(
                job,
                status="completed",
                progress=100,
                current_step="completed",
                completed_at=completed_at,
                stats=stats,
            )
            await self.uow.knowledge_sources.update(
                source,
                status="completed",
                connection_status="connected",
                sync_progress=100,
                last_synced_at=completed_at.isoformat(),
                last_error=None,
                metadata_={
                    "items": [
                        {key: value for key, value in item.items() if key != "content"}
                        for item in sync_result.get("items", [])
                    ],
                    **stats,
                },
            )
            await self.uow.commit()
            sync_result["progress"] = 100
            sync_result["stats"] = stats
        except Exception as exc:
            await self.uow.sync_jobs.update(
                job,
                status="failed",
                progress=0,
                current_step="failed",
                completed_at=datetime.now(UTC),
                error_message=str(exc),
            )
            await self.uow.knowledge_sources.update(
                source,
                status="failed",
                sync_progress=0,
                last_error=str(exc),
                error_count=(source.error_count or 0) + 1,
            )
            await self.uow.commit()
            raise

        sync_result["db_job_id"] = str(job.id)
        await self._maybe_trigger_runtime(
            str(source.project_id), trigger="source_synced", include_active=True
        )
        return sync_result

    async def _persist_website_items(self, source, items: list[dict]) -> int:
        knowledge_base_id = source.config.get("knowledge_base_id")
        knowledge_base = None
        if knowledge_base_id:
            try:
                knowledge_base = await self.uow.knowledge_bases.get(uuid.UUID(knowledge_base_id))
            except (TypeError, ValueError):
                knowledge_base = None
            if knowledge_base is None or knowledge_base.project_id != source.project_id:
                raise ValueError("Website source knowledge_base_id is invalid")
        else:
            knowledge_bases = await self.uow.knowledge_bases.get_by_project(source.project_id)
            knowledge_base = knowledge_bases[0] if knowledge_bases else None
            if knowledge_base is None:
                knowledge_base = await self.uow.knowledge_bases.create(
                    name="Website Sources",
                    description="Content synchronized from website sources",
                    project_id=source.project_id,
                    config={},
                )

        synced = 0
        for item in items:
            url = item.get("url")
            content = item.get("content")
            if not isinstance(url, str) or not isinstance(content, str) or not content.strip():
                continue
            content = content.replace("\x00", "").strip()
            chunks = chunk_document(content, source=url, document_id=None)
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            metadata = {
                "source_type": "website",
                "content_type": item.get("content_type"),
                "content_length": len(content),
            }
            existing = await self.uow.documents.get_by_source(knowledge_base.id, url)
            values = {
                "title": str(item.get("title") or url)[:512],
                "content": content,
                "chunk_count": len(chunks),
                "doc_metadata": metadata,
                "content_hash": content_hash,
            }
            if existing:
                await self.uow.documents.update(existing, **values)
            else:
                await self.uow.documents.create(
                    source=url,
                    knowledge_base_id=knowledge_base.id,
                    **values,
                )
            synced += 1
        return synced

    async def cancel_sync(self, job_id: str) -> dict:
        job = await self.uow.sync_jobs.get(job_id)
        if not job:
            raise ValueError("Sync job not found")
        updated = await self.uow.sync_jobs.update(
            job,
            status="cancelled",
            completed_at=datetime.now(),
        )
        await self.uow.commit()
        return {
            "id": str(updated.id),
            "status": updated.status,
        }

    async def get_sync_job(self, job_id: str) -> dict | None:
        job = await self.uow.sync_jobs.get(job_id)
        if not job:
            return None
        return {
            "id": str(job.id),
            "source_id": str(job.source_id),
            "project_id": str(job.project_id),
            "status": job.status,
            "progress": job.progress,
            "current_step": job.current_step,
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            "error_message": job.error_message,
            "stats": job.stats,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        }

    async def list_sync_jobs(self, source_id: str) -> list[dict]:
        jobs = await self.uow.sync_jobs.get_by_source(source_id)
        return [
            {
                "id": str(j.id),
                "source_id": str(j.source_id),
                "project_id": str(j.project_id),
                "status": j.status,
                "progress": j.progress,
                "current_step": j.current_step,
                "started_at": j.started_at.isoformat() if j.started_at else None,
                "completed_at": j.completed_at.isoformat() if j.completed_at else None,
                "error_message": j.error_message,
                "stats": j.stats,
                "created_at": j.created_at.isoformat() if j.created_at else None,
                "updated_at": j.updated_at.isoformat() if j.updated_at else None,
            }
            for j in jobs
        ]

    async def _maybe_trigger_runtime(
        self,
        project_id: str,
        trigger: str,
        *,
        include_active: bool = False,
    ) -> None:
        from app.services.runtimes import RuntimeService
        service = RuntimeService(self.uow)
        runtime = await service.get_by_project(project_id)
        rebuildable_statuses = {"queued", "failed", "cancelled"}
        if include_active:
            rebuildable_statuses.add("active")
        if runtime and runtime.get("status") in rebuildable_statuses:
            await service.enqueue_build(runtime["id"], trigger=trigger)
