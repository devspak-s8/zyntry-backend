import uuid
from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock

from app.services.runtimes import RuntimeService
from app.services.health import HealthService


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
    def __init__(self, runtime):
        self.runtimes = FakeRuntimeRepo(runtime)

    async def commit(self):
        return None


@pytest.mark.asyncio
async def test_enqueue_build_falls_back_to_active_when_celery_is_unavailable(monkeypatch):
    runtime = SimpleNamespace(
        id=uuid.uuid4(),
        status="queued",
        last_build_started=None,
        error_message=None,
    )
    uow = FakeUnitOfWork(runtime)
    service = RuntimeService(uow)

    class FakeBuildTask:
        def delay(self, *_args, **_kwargs):
            raise RuntimeError("broker unavailable")

    monkeypatch.setattr("app.tasks.runtimes.build_runtime_task", FakeBuildTask())
    monkeypatch.setattr("app.main.manager.broadcast", AsyncMock(return_value=None))

    result = await service.enqueue_build(str(runtime.id), trigger="manual")

    assert result["status"] == "active"
    assert runtime.status == "active"


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
