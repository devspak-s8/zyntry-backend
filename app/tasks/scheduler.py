from __future__ import annotations

from app.workers.celery_app import celery_app
from app.core.database import run_async


@celery_app.task(name="app.tasks.scheduler.run_scheduled_syncs")
def run_scheduled_syncs() -> dict:
    async def _run() -> dict:
        from app.core.database import get_session
        from app.repositories import UnitOfWork
        from app.services.scheduler import SchedulerService

        async for session in get_session():
            uow = UnitOfWork(session)
            service = SchedulerService(uow)
            result = await service.run_pending()
            return result

    return run_async(_run())


@celery_app.task(name="app.tasks.scheduler.run_scheduled_workflows")
def run_scheduled_workflows() -> dict:
    async def _run() -> dict:
        from app.core.database import get_session
        from app.repositories import UnitOfWork
        from app.services.scheduler import SchedulerService

        async for session in get_session():
            return await SchedulerService(UnitOfWork(session)).run_pending_workflows()
    return run_async(_run())


@celery_app.task(name="app.tasks.scheduler.retry_failed_sync")
def retry_failed_sync(job_id: str) -> dict:
    async def _retry() -> dict:
        from app.core.database import get_session
        from app.repositories import UnitOfWork
        from app.services.scheduler import SchedulerService

        async for session in get_session():
            uow = UnitOfWork(session)
            service = SchedulerService(uow)
            result = await service.retry_sync_job(job_id, max_retries=3)
            return result

    return run_async(_retry())


@celery_app.task(name="app.tasks.scheduler.priority_sync")
def priority_sync(source_id: str) -> dict:
    async def _priority() -> dict:
        from app.core.database import get_session
        from app.repositories import UnitOfWork
        from app.services.knowledge import KnowledgeService

        async for session in get_session():
            uow = UnitOfWork(session)
            service = KnowledgeService(uow)
            result = await service.sync_source(source_id=source_id, options={"priority": True})
            return result

    return run_async(_priority())
