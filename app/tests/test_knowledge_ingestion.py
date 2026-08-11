from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import httpx
import pytest
from fastapi import UploadFile

from app.api.v1.knowledge import router as knowledge_router
from app.services.connectors.website import WebsiteConnector
from app.services.knowledge import KnowledgeService


@pytest.mark.asyncio
async def test_upload_endpoint_accepts_real_multipart_upload(monkeypatch) -> None:
    service = SimpleNamespace(
        upload_file=AsyncMock(
            return_value={
                "id": str(uuid4()),
                "title": "notes.txt",
                "source": "notes.txt",
                "knowledge_base_id": str(uuid4()),
                "chunk_count": 1,
            }
        )
    )
    monkeypatch.setattr(knowledge_router, "UnitOfWork", lambda db: object())
    monkeypatch.setattr(knowledge_router, "KnowledgeService", lambda uow: service)
    upload = UploadFile(file=BytesIO(b"hello knowledge"), filename="notes.txt")

    response = await knowledge_router.upload_document_file(
        file=upload,
        title="notes.txt",
        knowledge_base_id=str(uuid4()),
        current_user=SimpleNamespace(),
        db=SimpleNamespace(),
        source=None,
    )

    assert response.title == "notes.txt"
    service.upload_file.assert_awaited_once()
    assert service.upload_file.await_args.kwargs["content"] == b"hello knowledge"


@pytest.mark.asyncio
async def test_website_connector_crawls_only_same_origin_pages() -> None:
    connector = WebsiteConnector(
        project_id=str(uuid4()),
        source_id=str(uuid4()),
        config={"url": "https://example.com/", "max_pages": 5},
    )
    root = httpx.Response(
        200,
        request=httpx.Request("GET", "https://example.com/"),
        headers={"content-type": "text/html"},
        text=(
            "<html><head><title>Home</title></head><body>Home content"
            '<a href="/docs">Docs</a><a href="https://other.example/out">Away</a>'
            "</body></html>"
        ),
    )
    docs = httpx.Response(
        200,
        request=httpx.Request("GET", "https://example.com/docs"),
        headers={"content-type": "text/html"},
        text="<html><head><title>Docs</title></head><body>Documentation</body></html>",
    )
    connector._fetch = AsyncMock(side_effect=[root, docs])  # type: ignore[method-assign]

    items = await connector._crawl(include_content=True)

    assert [item["url"] for item in items] == [
        "https://example.com/",
        "https://example.com/docs",
    ]
    assert items[1]["content"] == "Docs\nDocumentation"


@pytest.mark.asyncio
async def test_website_connector_rejects_local_addresses() -> None:
    connector = WebsiteConnector(
        project_id=str(uuid4()),
        source_id=str(uuid4()),
        config={"url": "http://127.0.0.1/internal"},
    )

    result = await connector.test()

    assert result["success"] is False
    assert "Private or local" in result["message"]


@pytest.mark.asyncio
async def test_website_items_are_persisted_and_chunked() -> None:
    project_id = uuid4()
    knowledge_base = SimpleNamespace(id=uuid4(), project_id=project_id)
    source = SimpleNamespace(project_id=project_id, config={})
    documents = SimpleNamespace(
        get_by_source=AsyncMock(return_value=None),
        create=AsyncMock(return_value=SimpleNamespace(id=uuid4())),
        update=AsyncMock(),
    )
    uow = SimpleNamespace(
        knowledge_bases=SimpleNamespace(
            get_by_project=AsyncMock(return_value=[knowledge_base]),
            get=AsyncMock(),
            create=AsyncMock(),
        ),
        documents=documents,
    )
    service = KnowledgeService(uow)

    count = await service._persist_website_items(
        source,
        [{
            "url": "https://example.com/docs",
            "title": "Docs",
            "content": "A useful documentation page with enough text to index.",
            "content_type": "text/html",
        }],
    )

    assert count == 1
    documents.create.assert_awaited_once()
    values = documents.create.await_args.kwargs
    assert values["source"] == "https://example.com/docs"
    assert values["content"]
    assert values["chunk_count"] >= 1
    assert len(values["content_hash"]) == 64


@pytest.mark.asyncio
async def test_sync_marks_source_and_job_completed() -> None:
    project_id = uuid4()
    source = SimpleNamespace(
        id=uuid4(),
        project_id=project_id,
        source_type="website",
        config={"url": "https://example.com"},
        credentials_encrypted=None,
        error_count=0,
    )
    job = SimpleNamespace(id=uuid4())
    connector = SimpleNamespace(
        sync=AsyncMock(return_value={"status": "completed", "total": 1, "items": []})
    )
    uow = SimpleNamespace(
        knowledge_sources=SimpleNamespace(
            get=AsyncMock(return_value=source),
            update=AsyncMock(),
        ),
        sync_jobs=SimpleNamespace(create=AsyncMock(return_value=job), update=AsyncMock()),
        commit=AsyncMock(),
    )
    service = KnowledgeService(uow)
    service.get_connector = Mock(return_value=connector)  # type: ignore[method-assign]
    service._persist_website_items = AsyncMock(return_value=1)  # type: ignore[method-assign]
    service._maybe_trigger_runtime = AsyncMock()  # type: ignore[method-assign]

    result = await service.sync_source(str(source.id))

    assert result["status"] == "completed"
    assert result["progress"] == 100
    assert result["stats"]["documents_synced"] == 1
    assert any(
        call.kwargs.get("status") == "completed"
        for call in uow.knowledge_sources.update.await_args_list
    )
    assert any(
        call.kwargs.get("status") == "completed"
        for call in uow.sync_jobs.update.await_args_list
    )
