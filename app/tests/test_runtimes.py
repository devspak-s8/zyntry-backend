import uuid
from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock, Mock

from app.services.runtimes import RuntimeCreationConflict, RuntimeService
from app.services.health import HealthService
from app.schemas.runtimes import RuntimeCreate
from app.repositories import UnitOfWork


class FakeRuntimeRepo:
    def __init__(self, runtime):
        self.runtime = runtime

    async def get(self, runtime_id):
        return self.runtime

    async def update(self, instance, **kwargs):
        for key, value in kwargs.items():
            setattr(instance, key, value)
        return instance


class FakeUnitOfWork:
    def __init__(self, runtime, integrations=None):
        self.runtimes = FakeRuntimeRepo(runtime)
        self.runtime_integrations = SimpleNamespace(
            get_by_runtime=AsyncMock(return_value=integrations or [])
        )

    async def commit(self):
        return None


@pytest.mark.asyncio
async def test_enqueue_build_queues_worker_and_keeps_runtime_building(monkeypatch):
    runtime = SimpleNamespace(
        id=uuid.uuid4(),
        status="queued",
        last_build_started=None,
        error_message=None,
    )
    uow = FakeUnitOfWork(runtime)
    service = RuntimeService(uow)

    class FakeBuildTask:
        def __init__(self):
            self.delay = Mock()

    task = FakeBuildTask()
    monkeypatch.setattr("app.tasks.runtimes.build_runtime_task", task)

    result = await service.enqueue_build(str(runtime.id), trigger="manual")

    assert result["status"] == "building"
    assert runtime.status == "building"
    task.delay.assert_called_once_with(str(runtime.id), trigger="manual")


@pytest.mark.asyncio
async def test_enqueue_build_waits_for_required_company_connections() -> None:
    runtime = SimpleNamespace(
        id=uuid.uuid4(),
        status="preconfigured",
        last_build_started=None,
        error_message=None,
    )
    pending_company_connection = SimpleNamespace(
        integration_slug="github",
        is_enabled=True,
        connection_required=True,
        connection_status="connection_required",
    )
    service = RuntimeService(FakeUnitOfWork(runtime, [pending_company_connection]))

    result = await service.enqueue_build(str(runtime.id), trigger="project_wizard")

    assert result["status"] == "awaiting_connections"
    assert result["required_connections"] == ["github"]
    assert runtime.status == "awaiting_connections"


@pytest.mark.asyncio
async def test_runtime_health_contains_response_contract_fields():
    runtime = SimpleNamespace(
        id=uuid.uuid4(), status="active", health=100.0, version="1",
        last_build_completed=None, last_propagated=None, documents=2,
        chunks=4, embeddings=4, index_size=4,
    )
    uow = SimpleNamespace(
        runtimes=SimpleNamespace(get=AsyncMock(return_value=runtime)),
        session=SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [])))),
    )
    health = await HealthService(uow).get_runtime_health(str(runtime.id))
    assert health["version"] == "1"
    assert health["documents"] == 2
    assert health["errors"] == 0


@pytest.mark.asyncio
async def test_runtime_name_check_reports_duplicate_for_user(db_session):
    uow = UnitOfWork(db_session)
    user = await uow.users.create(email="duplicate_name@zyntry.space", name="Duplicate")
    await uow.runtimes.create(user_id=user.id, name="Atlas Runtime")
    await uow.commit()

    service = RuntimeService(uow)
    result = await service.inspect_name(user.id, " atlas runtime ")

    assert result["available"] is False
    assert result["conflict_code"] == "runtime_name_already_exists"
    assert result["existing_runtime_name"] == "Atlas Runtime"
    with pytest.raises(RuntimeCreationConflict):
        await service.get_or_create(
            RuntimeCreate(name="Atlas Runtime"),
            default_user_id=user.id,
        )
