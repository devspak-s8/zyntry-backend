from __future__ import annotations

from app.workers.celery_app import celery_app


@celery_app.task(name="app.tasks.embeddings.index_document")
def index_document(document_id: str) -> dict[str, str]:
    return {
        "document_id": document_id,
        "status": "unsupported",
        "error": "Document indexing is handled by the knowledge service; this task is not wired.",
    }


@celery_app.task(name="app.tasks.knowledge.ingest")
def ingest_knowledge(knowledge_base_id: str) -> dict[str, str]:
    return {
        "knowledge_base_id": knowledge_base_id,
        "status": "unsupported",
        "error": "Knowledge ingestion is handled by the knowledge service; this task is not wired.",
    }


@celery_app.task(name="app.tasks.knowledge.start_source_sync")
def start_source_sync_task(source_id: str) -> dict:
    return {
        "source_id": source_id,
        "status": "unsupported",
        "code": "task_not_implemented",
        "message": "Source synchronization must be started through KnowledgeService.",
    }


@celery_app.task(name="app.tasks.knowledge.cancel_source_sync")
def cancel_source_sync_task(job_id: str) -> dict:
    return {
        "job_id": job_id,
        "status": "unsupported",
        "code": "task_not_implemented",
        "message": "Source synchronization cancellation must be handled by the knowledge service.",
    }


@celery_app.task(name="app.tasks.knowledge.test_source_connection")
def test_source_connection_task(source_id: str) -> dict:
    return {
        "source_id": source_id,
        "success": False,
        "status": "unsupported",
        "code": "task_not_implemented",
        "message": "Source connection tests must run through KnowledgeService.test_source.",
    }


@celery_app.task(name="app.tasks.knowledge.discover_source_metadata")
def discover_source_metadata_task(source_id: str) -> dict:
    return {
        "source_id": source_id,
        "status": "unsupported",
        "code": "task_not_implemented",
        "message": "Source discovery must run through KnowledgeService.discover_source.",
        "items": [],
        "total": 0,
    }
