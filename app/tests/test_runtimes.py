import uuid
from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock

from app.services.runtimes import RuntimeService


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
