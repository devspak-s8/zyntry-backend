from __future__ import annotations

from app.workers.celery_app import celery_app


@celery_app.task(name="app.tasks.embeddings.index_document")
def index_document(document_id: str) -> None: ...


@celery_app.task(name="app.tasks.knowledge.ingest")
def ingest_knowledge(knowledge_base_id: str) -> None: ...


@celery_app.task(name="app.tasks.knowledge.start_source_sync")
def start_source_sync_task(source_id: str) -> dict:
    return {"source_id": source_id, "status": "queued"}


@celery_app.task(name="app.tasks.knowledge.cancel_source_sync")
def cancel_source_sync_task(job_id: str) -> dict:
    return {"job_id": job_id, "status": "cancelled"}


@celery_app.task(name="app.tasks.knowledge.test_source_connection")
def test_source_connection_task(source_id: str) -> dict:
    return {"source_id": source_id, "success": True, "message": "stub"}


@celery_app.task(name="app.tasks.knowledge.discover_source_metadata")
def discover_source_metadata_task(source_id: str) -> dict:
    return {"source_id": source_id, "items": [], "total": 0}
