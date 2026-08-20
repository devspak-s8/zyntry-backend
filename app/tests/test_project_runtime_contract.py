from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api.v1.projects.router import create_project_runtime
from app.schemas.projects import ProjectUpdate
from app.schemas.runtimes import RuntimeCreate


def _runtime_response(
    *, project_id: uuid.UUID, user_id: uuid.UUID, organization_id: uuid.UUID
) -> dict:
    now = "2026-08-20T09:40:33+00:00"
    return {
        "id": str(uuid.uuid4()),
        "user_id": str(user_id),
        "name": "Project Runtime",
        "environment": "development",
        "project_id": str(project_id),
        "organization_id": str(organization_id),
        "status": "active",
        "version": "1",
        "provider": "openai",
        "model": "gpt-4o",
        "fallback_models": [],
        "routing_strategy": "balanced",
        "embedding_model": "text-embedding-3-small",
        "vector_store": "pgvector",
        "chunk_size": 512,
        "chunk_overlap": 64,
        "documents": 0,
        "chunks": 0,
        "embeddings": 0,
        "index_size": 0,
        "last_build_started": None,
        "last_build_completed": None,
        "last_propagated": None,
        "health": 100.0,
        "error_message": None,
        "api_key_id": None,
        "system_instructions": None,
        "security_policies": {},
        "config": {},
        "metadata": {},
        "created_at": now,
        "updated_at": now,
    }


def test_project_update_is_a_partial_schema() -> None:
    update = ProjectUpdate(description="Updated description")

    assert update.model_dump(exclude_unset=True) == {"description": "Updated description"}


@pytest.mark.asyncio
async def test_project_runtime_endpoint_derives_ownership_from_project(monkeypatch) -> None:
    project_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    user_id = uuid.uuid4()
    project = SimpleNamespace(id=project_id, organization_id=organization_id)
    user = SimpleNamespace(id=user_id, organization_id=organization_id)
    db = SimpleNamespace(get=AsyncMock(return_value=project))
    get_or_create = AsyncMock(
        return_value=_runtime_response(
            project_id=project_id,
            user_id=user_id,
            organization_id=organization_id,
        )
    )
    monkeypatch.setattr(
        "app.api.v1.projects.router.RuntimeService.get_or_create",
        get_or_create,
    )

    response = await create_project_runtime(
        str(project_id),
        RuntimeCreate(
            name="Project Runtime",
            project_id=uuid.uuid4(),
            organization_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
        ),
        user,
        db,
    )

    runtime_data = get_or_create.await_args.args[0]
    assert runtime_data.project_id == project_id
    assert runtime_data.organization_id == organization_id
    assert runtime_data.user_id == user_id
    assert response.project_id == project_id
