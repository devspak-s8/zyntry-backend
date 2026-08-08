from __future__ import annotations

from datetime import datetime, timezone

from app.workers.celery_app import celery_app
from app.workers.runtime_worker import RuntimeWorker


@celery_app.task(name="app.tasks.runtimes.build_runtime")
def build_runtime_task(runtime_id: str, trigger: str = "manual") -> dict:
    worker = RuntimeWorker(runtime_id=runtime_id, trigger=trigger)
    from app.core.database import run_async

    run_async(worker.run())
    return {"runtime_id": runtime_id, "status": "completed"}


@celery_app.task(name="app.tasks.runtimes.propagate_runtime")
def propagate_runtime_task(runtime_id: str) -> dict:
    async def _propagate() -> dict:
        from app.core.database import get_session
        from app.repositories import UnitOfWork
        from app.services.runtimes import RuntimeService

        async for session in get_session():
            uow = UnitOfWork(session)
            service = RuntimeService(uow)
            runtime = await uow.runtimes.get(runtime_id)
            if not runtime:
                return {"runtime_id": runtime_id, "status": "not_found"}
            from app.main import manager

            await manager.broadcast({"type": "PropagationStarted", "runtime_id": runtime_id})
            changes = await service.detect_changes(runtime_id)
            if changes.get("existing_chunks", 0) == 0:
                await service.enqueue_build(runtime_id, trigger="propagation")
                return {"runtime_id": runtime_id, "status": "full_rebuild_queued"}
            runtime.last_propagated = datetime.now(timezone.utc)
            await uow.runtimes.update(runtime, last_propagated=datetime.now(timezone.utc))
            await uow.session.commit()
            from app.main import manager

            await manager.broadcast({"type": "PropagationCompleted", "runtime_id": runtime_id})
            return {"runtime_id": runtime_id, "status": "completed"}

    from app.core.database import run_async

    return run_async(_propagate())
