from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.api.v1.features.dependencies import require_feature
from app.core.database import get_session
from app.models.users import User
from app.repositories import UnitOfWork
from app.schemas.documents import FileUploadCreate
from app.schemas.knowledge import (
    DocumentCreate,
    DocumentRead,
    KnowledgeBaseCreate,
    KnowledgeBaseRead,
    KnowledgeSourceCreate,
    KnowledgeSourceRead,
    KnowledgeSourceUpdate,
    SyncJobRead,
)
from app.services.knowledge import KnowledgeService

router = APIRouter(prefix="/knowledge", tags=["knowledge"])
SOURCE_GUARD = [Depends(require_feature("knowledge_sources"))]


@router.get("", response_model=list[KnowledgeBaseRead])
async def list_knowledge_bases(
    current_user: Annotated[User, Depends(get_current_user)],
    project_id: str,
    db: AsyncSession = Depends(get_session),
) -> list[KnowledgeBaseRead]:
    uow = UnitOfWork(db)
    service = KnowledgeService(uow)
    kbs = await service.list_knowledge_bases(project_id)
    return [
        KnowledgeBaseRead(
            id=kb["id"],
            name=kb["name"],
            description=kb.get("description"),
            project_id=kb["project_id"],
            config=kb.get("config", {}),
            created_at=kb.get("created_at", datetime.now()),
            updated_at=kb.get("updated_at", datetime.now()),
        )
        for kb in kbs
    ]


@router.post("", response_model=KnowledgeBaseRead, status_code=status.HTTP_201_CREATED)
async def create_knowledge_base(
    body: KnowledgeBaseCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> KnowledgeBaseRead:
    uow = UnitOfWork(db)
    service = KnowledgeService(uow)
    kb = await service.create_knowledge_base(body)
    return KnowledgeBaseRead(
        id=kb["id"],
        name=kb["name"],
        description=kb.get("description"),
        project_id=kb["project_id"],
        config=kb.get("config", {}),
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


@router.post("/documents", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def upload_document(
    body: DocumentCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> DocumentRead:
    uow = UnitOfWork(db)
    service = KnowledgeService(uow)
    doc = await service.upload_document(body)
    return DocumentRead(
        id=doc["id"],
        title=doc["title"],
        content=None,
        source=doc.get("source"),
        knowledge_base_id=doc["knowledge_base_id"],
        chunk_count=doc.get("chunk_count", 0),
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


@router.post("/documents/upload", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def upload_document_file(
    file: Annotated[UploadFile, File()],
    title: Annotated[str, Form(min_length=1)],
    knowledge_base_id: Annotated[str, Form(min_length=1)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
    source: Annotated[str | None, Form()] = None,
) -> DocumentRead:
    body = FileUploadCreate(
        title=title.strip(),
        knowledge_base_id=knowledge_base_id.strip(),
        source=source.strip() if source and source.strip() else None,
    )

    uow = UnitOfWork(db)
    service = KnowledgeService(uow)
    content = await file.read()
    doc = await service.upload_file(
        content=content,
        filename=file.filename or "uploaded_file",
        content_type=file.content_type or "application/octet-stream",
        title=body.title,
        knowledge_base_id=body.knowledge_base_id,
        source=body.source,
    )
    return DocumentRead(
        id=doc["id"],
        title=doc["title"],
        content=None,
        source=doc.get("source"),
        knowledge_base_id=doc["knowledge_base_id"],
        chunk_count=doc.get("chunk_count", 0),
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


@router.get("/{knowledge_base_id}/documents", response_model=list[DocumentRead])
async def list_documents(
    knowledge_base_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> list[DocumentRead]:
    uow = UnitOfWork(db)
    service = KnowledgeService(uow)
    docs = await service.list_documents(knowledge_base_id)
    return [
        DocumentRead(
            id=d["id"],
            title=d["title"],
            content=None,
            source=d.get("source"),
            knowledge_base_id=knowledge_base_id,
            chunk_count=d.get("chunk_count", 0),
            created_at=d.get("created_at", datetime.now()),
            updated_at=d.get("updated_at", datetime.now()),
        )
        for d in docs
    ]


@router.get("/sources", response_model=list[KnowledgeSourceRead], dependencies=SOURCE_GUARD)
async def list_knowledge_sources(
    current_user: Annotated[User, Depends(get_current_user)],
    project_id: str,
    db: AsyncSession = Depends(get_session),
) -> list[KnowledgeSourceRead]:
    uow = UnitOfWork(db)
    service = KnowledgeService(uow)
    sources = await service.list_sources(project_id)
    return [
        KnowledgeSourceRead(
            id=s["id"],
            project_id=s["project_id"],
            source_type=s["source_type"],
            display_name=s["display_name"],
            config=s.get("config", {}),
            sync_frequency=s.get("sync_frequency", "manual"),
            last_synced_at=s.get("last_synced_at"),
            status=s.get("status", "pending"),
            is_active=s.get("is_active", True),
            connection_status=s.get("connection_status", "pending"),
            last_error=s.get("last_error"),
            error_count=s.get("error_count", 0),
            sync_progress=s.get("sync_progress", 0),
            metadata=s.get("metadata", {}),
            created_at=s.get("created_at", datetime.now()),
            updated_at=s.get("updated_at", datetime.now()),
        )
        for s in sources
    ]


@router.post("/sources", response_model=KnowledgeSourceRead, status_code=status.HTTP_201_CREATED, dependencies=SOURCE_GUARD)
async def create_knowledge_source(
    body: KnowledgeSourceCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> KnowledgeSourceRead:
    uow = UnitOfWork(db)
    service = KnowledgeService(uow)
    source = await service.create_source(body)
    return KnowledgeSourceRead(
        id=source["id"],
        project_id=source["project_id"],
        source_type=source["source_type"],
        display_name=source["display_name"],
        config=source.get("config", {}),
        sync_frequency=source.get("sync_frequency", "manual"),
        last_synced_at=source.get("last_synced_at"),
        status=source.get("status", "pending"),
        is_active=source.get("is_active", True),
        connection_status=source.get("connection_status", "pending"),
        last_error=source.get("last_error"),
        error_count=source.get("error_count", 0),
        sync_progress=source.get("sync_progress", 0),
        metadata=source.get("metadata", {}),
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


@router.patch("/sources/{source_id}", response_model=KnowledgeSourceRead, dependencies=SOURCE_GUARD)
async def update_knowledge_source(
    source_id: str,
    body: KnowledgeSourceUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> KnowledgeSourceRead:
    uow = UnitOfWork(db)
    service = KnowledgeService(uow)
    source = await service.update_source(source_id, body)
    return KnowledgeSourceRead(
        id=source["id"],
        project_id=source["project_id"],
        source_type=source["source_type"],
        display_name=source["display_name"],
        config=source.get("config", {}),
        sync_frequency=source.get("sync_frequency", "manual"),
        last_synced_at=source.get("last_synced_at"),
        status=source.get("status", "pending"),
        is_active=source.get("is_active", True),
        connection_status=source.get("connection_status", "pending"),
        last_error=source.get("last_error"),
        error_count=source.get("error_count", 0),
        sync_progress=source.get("sync_progress", 0),
        metadata=source.get("metadata", {}),
        created_at=source.get("created_at", datetime.now()),
        updated_at=source.get("updated_at", datetime.now()),
    )


@router.delete("/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=SOURCE_GUARD)
async def delete_knowledge_source(
    source_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> None:
    uow = UnitOfWork(db)
    service = KnowledgeService(uow)
    await service.delete_source(source_id)


@router.post("/test-connection", tags=["knowledge"], dependencies=SOURCE_GUARD)
async def test_source_connection(
    body: dict,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> dict:
    uow = UnitOfWork(db)
    service = KnowledgeService(uow)
    source_id = body.get("source_id")
    if not source_id:
        raise HTTPException(status_code=400, detail="source_id is required")
    try:
        result = await service.test_source(source_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return result


@router.post("/discover", tags=["knowledge"], dependencies=SOURCE_GUARD)
async def discover_source_metadata(
    body: dict,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> dict:
    uow = UnitOfWork(db)
    service = KnowledgeService(uow)
    source_id = body.get("source_id")
    if not source_id:
        raise HTTPException(status_code=400, detail="source_id is required")
    try:
        result = await service.discover_source(source_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return result


@router.post("/sources/{source_id}/sync", response_model=SyncJobRead, tags=["knowledge"], dependencies=SOURCE_GUARD)
async def sync_knowledge_source(
    source_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> SyncJobRead:
    uow = UnitOfWork(db)
    service = KnowledgeService(uow)
    result = await service.sync_source(source_id)
    job_id = result.get("db_job_id") or result.get("job_id") or source_id
    return SyncJobRead(
        id=job_id,
        source_id=source_id,
        project_id=result.get("project_id", ""),
        status=result.get("status", "queued"),
        progress=result.get("progress", 0),
        current_step=result.get("current_step"),
        started_at=datetime.now(),
        completed_at=None,
        error_message=None,
        stats=result.get("stats", {}),
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


@router.get("/sources/{source_id}/sync-jobs", response_model=list[SyncJobRead], tags=["knowledge"], dependencies=SOURCE_GUARD)
async def list_source_sync_jobs(
    source_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> list[SyncJobRead]:
    uow = UnitOfWork(db)
    service = KnowledgeService(uow)
    jobs = await service.list_sync_jobs(source_id)
    return [
        SyncJobRead(
            id=j["id"],
            source_id=j["source_id"],
            project_id=j["project_id"],
            status=j["status"],
            progress=j["progress"],
            current_step=j.get("current_step"),
            started_at=j.get("started_at"),
            completed_at=j.get("completed_at"),
            error_message=j.get("error_message"),
            stats=j.get("stats", {}),
            created_at=j.get("created_at", datetime.now()),
            updated_at=j.get("updated_at", datetime.now()),
        )
        for j in jobs
    ]


@router.get("/sync-jobs/{job_id}", response_model=SyncJobRead, tags=["knowledge"], dependencies=SOURCE_GUARD)
async def get_sync_job(
    job_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> SyncJobRead:
    uow = UnitOfWork(db)
    service = KnowledgeService(uow)
    job = await service.get_sync_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Sync job not found")
    return SyncJobRead(
        id=job["id"],
        source_id=job["source_id"],
        project_id=job["project_id"],
        status=job["status"],
        progress=job["progress"],
        current_step=job.get("current_step"),
        started_at=job.get("started_at"),
        completed_at=job.get("completed_at"),
        error_message=job.get("error_message"),
        stats=job.get("stats", {}),
        created_at=job.get("created_at", datetime.now()),
        updated_at=job.get("updated_at", datetime.now()),
    )


@router.post("/sync-jobs/{job_id}/cancel", response_model=SyncJobRead, tags=["knowledge"], dependencies=SOURCE_GUARD)
async def cancel_sync_job(
    job_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> SyncJobRead:
    uow = UnitOfWork(db)
    service = KnowledgeService(uow)
    result = await service.cancel_sync(job_id)
    return SyncJobRead(
        id=result["id"],
        source_id="",
        project_id="",
        status=result["status"],
        progress=0,
        current_step=None,
        started_at=None,
        completed_at=None,
        error_message=None,
        stats={},
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
