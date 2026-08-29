from __future__ import annotations

import secrets
from datetime import datetime, timezone

from app.workers.celery_app import celery_app
from app.workers.runtime_worker import RuntimeWorker


@celery_app.task(name="app.tasks.runtimes.build_runtime")
def build_runtime_task(runtime_id: str, trigger: str = "manual") -> dict:
    """Build a runtime once at a time, even when a task is delivered twice.

    Celery is at-least-once delivery by design.  A duplicate build used to
    delete the first build's chunks and race its status updates.  A short-lived
    distributed lock makes duplicate deliveries harmless while retaining a
    safe availability fallback when Redis is temporarily unavailable.
    """
    from app.core.database import run_async

    async def _run() -> dict:
        from app.core.redis import redis_client

        lock_key = f"runtime:build:{runtime_id}"
        lock_token = secrets.token_urlsafe(24)
        acquired = True
        redis_available = True
        try:
            acquired = bool(await redis_client.set(lock_key, lock_token, nx=True, ex=3600))
        except Exception:
            # Redis is coordination, not the source of truth.  If it is down,
            # execute the build and let the database remain authoritative.
            redis_available = False

        if not acquired:
            return {"runtime_id": runtime_id, "status": "already_running"}

        try:
            worker = RuntimeWorker(runtime_id=runtime_id, trigger=trigger)
            await worker.run()
            return {"runtime_id": runtime_id, "status": "completed"}
        finally:
            if redis_available:
                try:
                    # Delete only our lock; a late task must never release a
                    # lock acquired by a newer build.
                    await redis_client.eval(
                        "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end",
                        1,
                        lock_key,
                        lock_token,
                    )
                except Exception:
                    pass

    return run_async(_run())


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

            await manager.send_to_user(
                {"type": "PropagationStarted", "runtime_id": runtime_id},
                str(runtime.user_id),
            )
            changes = await service.detect_changes(runtime_id)
            if changes.get("existing_chunks", 0) == 0:
                await service.enqueue_build(runtime_id, trigger="propagation")
                return {"runtime_id": runtime_id, "status": "full_rebuild_queued"}
            runtime.last_propagated = datetime.now(timezone.utc)
            await uow.runtimes.update(runtime, last_propagated=datetime.now(timezone.utc))
            await uow.session.commit()
            from app.main import manager

            await manager.send_to_user(
                {"type": "PropagationCompleted", "runtime_id": runtime_id},
                str(runtime.user_id),
            )
            return {"runtime_id": runtime_id, "status": "completed"}

    from app.core.database import run_async

    return run_async(_propagate())
