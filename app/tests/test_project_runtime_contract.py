from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api.v1.projects.router import (
    build_project_runtime,
    configure_project,
    create_project_runtime,
    update_project,
)
from app.repositories import UnitOfWork
from app.schemas.integrations import RuntimeIntegrationCreate
from app.schemas.projects import ProjectConfigUpdate, ProjectUpdate
from app.schemas.runtimes import RuntimeCreate
from app.services.integrations.service import IntegrationService
from app.services.runtimes import RuntimeService


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


@pytest.mark.asyncio
async def test_wizard_attaches_configures_and_builds_the_same_runtime(
    db_session, monkeypatch
) -> None:
    uow = UnitOfWork(db_session)
    organization = await uow.organizations.create(name="Wizard Org", slug="wizard-org")
    await uow.commit()
    user = await uow.users.create(
        email="wizard@zyntry.space",
        name="Wizard User",
        organization_id=organization.id,
    )
    project = await uow.projects.create(
        name="Wizard Project",
        slug="wizard-project",
        organization_id=organization.id,
        settings={},
        status="ready",
    )
    await uow.commit()

    runtime_data = await RuntimeService(uow).get_or_create(
        RuntimeCreate(name="Onboarding Runtime"),
        default_user_id=user.id,
    )
    runtime_id = uuid.UUID(runtime_data["id"])
    await IntegrationService(uow).enable_runtime_integration(
        runtime_id,
        RuntimeIntegrationCreate(
            integration_slug="github",
            connection_mode="end_user_oauth",
            enabled_capabilities=["repository_search"],
        ),
    )
    monkeypatch.setattr(
        "app.api.v1.projects.router._invalidate_projects_cache",
        AsyncMock(return_value=None),
    )

    await update_project(
        str(project.id),
        ProjectUpdate(runtime_id=runtime_id),
        user,
        db_session,
    )
    attached_runtime = await uow.runtimes.get(runtime_id)
    assert attached_runtime.project_id == project.id
    assert attached_runtime.organization_id == organization.id

    configured = await configure_project(
        str(project.id),
        ProjectConfigUpdate(
            provider="anthropic",
            model="claude-sonnet-4",
            routing_strategy="balanced",
            system_instructions="Answer from connected repositories.",
            security_settings={"pii_redaction": True},
        ),
        user,
        db_session,
    )
    assert configured["runtime_id"] == str(runtime_id)
    assert attached_runtime.provider == "anthropic"
    assert attached_runtime.model == "claude-sonnet-4"
    assert attached_runtime.security_policies == {"pii_redaction": True}
    integrations = await IntegrationService(uow).list_runtime_integrations(runtime_id)
    assert [item.integration_slug for item in integrations] == ["github"]

    enqueue_build = AsyncMock(
        return_value={"runtime_id": str(runtime_id), "status": "active"}
    )
    monkeypatch.setattr(
        "app.api.v1.projects.router.RuntimeService.enqueue_build",
        enqueue_build,
    )
    built = await build_project_runtime(str(project.id), user, db_session)

    assert built["runtime_id"] == str(runtime_id)
    enqueue_build.assert_awaited_once_with(str(runtime_id), trigger="project_wizard")
