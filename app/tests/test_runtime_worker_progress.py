from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.workers.runtime_worker import RuntimeWorker


@pytest.mark.asyncio
async def test_runtime_worker_persists_live_build_stage_without_log_contents() -> None:
    runtime = SimpleNamespace(id=uuid4(), config={"runtime_plan": {"name": "Support"}})
    runtime_repo = SimpleNamespace(update=AsyncMock())
    uow = SimpleNamespace(
        runtimes=runtime_repo,
        session=SimpleNamespace(commit=AsyncMock()),
    )
    worker = RuntimeWorker(str(runtime.id))
    worker._runtime = runtime
    worker._uow = uow

    await worker._update_build_progress(stage="validate_sources", progress=8)

    assert runtime.config["runtime_plan"] == {"name": "Support"}
    assert runtime.config["build_stage"] == "validate_sources"
    assert runtime.config["build_progress"] == 8
    assert "build_updated_at" in runtime.config
    runtime_repo.update.assert_awaited_once_with(runtime, config=runtime.config)
    uow.session.commit.assert_awaited_once()
