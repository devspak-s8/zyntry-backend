from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.repositories import UnitOfWork
from app.services.knowledge import KnowledgeService


class SchedulerService:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def schedule_sync(
        self, source_id: str, frequency: str, options: dict | None = None
    ) -> dict:
        from app.models.knowledge import KnowledgeSource, SyncSchedule

        source = await self.uow.knowledge_sources.get(source_id)
        if not source:
            raise ValueError("Knowledge source not found")

        valid_frequencies = {"hourly", "daily", "weekly", "manual", "priority", "incremental"}
        if frequency not in valid_frequencies:
            raise ValueError(f"Invalid frequency: {frequency}. Must be one of {valid_frequencies}")

        now = datetime.now(timezone.utc)
        next_run_at = self._calculate_next_run(frequency, now)

        schedule = await self.uow.sync_schedules.create(
            source_id=source.id,
            project_id=source.project_id,
            frequency=frequency,
            status="active",
            last_run_at=None,
            next_run_at=next_run_at,
            retry_count=0,
            options=options or {},
        )
        await self.uow.commit()
        return {
            "id": str(schedule.id),
            "source_id": str(schedule.source_id),
            "project_id": str(schedule.project_id),
            "frequency": schedule.frequency,
            "status": schedule.status,
            "last_run_at": schedule.last_run_at.isoformat() if schedule.last_run_at else None,
            "next_run_at": schedule.next_run_at.isoformat() if schedule.next_run_at else None,
            "retry_count": schedule.retry_count,
            "options": schedule.options,
            "created_at": schedule.created_at.isoformat() if schedule.created_at else None,
        }

    async def run_pending(self) -> dict:
        now = datetime.now(timezone.utc)
        schedules = await self.uow.sync_schedules.list()
        active_schedules = [s for s in schedules if s.status == "active"]

        triggered = []
        for schedule in active_schedules:
            if schedule.next_run_at is None:
                continue
            if schedule.next_run_at > now:
                continue

            source = await self.uow.knowledge_sources.get(str(schedule.source_id))
            if not source or not source.is_active:
                continue

            try:
                knowledge_service = KnowledgeService(self.uow)
                sync_result = await knowledge_service.sync_source(
                    source_id=str(schedule.source_id),
                    options=schedule.options,
                )
                schedule.last_run_at = now
                schedule.next_run_at = self._calculate_next_run(schedule.frequency, now)
                await self.uow.sync_schedules.update(schedule, last_run_at=now, next_run_at=schedule.next_run_at)
                triggered.append({"source_id": str(schedule.source_id), "job_id": sync_result.get("db_job_id"), "status": "triggered"})
            except Exception as e:
                triggered.append({"source_id": str(schedule.source_id), "status": "error", "error": str(e)})

        await self.uow.commit()
        return {"triggered": triggered, "total": len(triggered)}

    async def retry_failed(self, max_retries: int = 3) -> dict:
        from app.models.knowledge import SyncJob

        jobs = await self.uow.sync_jobs.list()
        failed_jobs = [j for j in jobs if j.status == "failed" and j.retry_count < max_retries]

        retried = []
        for job in failed_jobs:
            if job.retry_after is not None and job.retry_after > datetime.now(timezone.utc):
                retried.append({"job_id": str(job.id), "source_id": str(job.source_id), "status": "waiting_for_backoff"})
                continue

            backoff_minutes = self._backoff_delay(job.retry_count)
            job.retry_count += 1
            job.status = "queued"
            job.error_message = None
            job.retry_after = datetime.now(timezone.utc) + timedelta(minutes=backoff_minutes)
            await self.uow.sync_jobs.update(
                job,
                status="queued",
                error_message=None,
                retry_count=job.retry_count,
                retry_after=job.retry_after,
            )
            retried.append({"job_id": str(job.id), "source_id": str(job.source_id), "retry_count": job.retry_count, "retry_after": job.retry_after.isoformat()})

        await self.uow.commit()
        return {"retried": retried, "total": len(retried), "max_retries": max_retries}

    async def retry_sync_job(self, job_id: str, max_retries: int = 3) -> dict:
        from app.models.knowledge import SyncJob

        job = await self.uow.sync_jobs.get(job_id)
        if not job:
            return {"job_id": job_id, "status": "not_found"}
        if job.status != "failed":
            return {"job_id": job_id, "status": "not_failed", "current_status": job.status}
        if job.retry_count >= max_retries:
            return {"job_id": job_id, "status": "max_retries_exceeded", "retry_count": job.retry_count}

        if job.retry_after is not None and job.retry_after > datetime.now(timezone.utc):
            return {"job_id": job_id, "status": "waiting_for_backoff", "retry_after": job.retry_after.isoformat()}

        backoff_minutes = self._backoff_delay(job.retry_count)
        job.retry_count += 1
        job.status = "queued"
        job.error_message = None
        job.retry_after = datetime.now(timezone.utc) + timedelta(minutes=backoff_minutes)
        await self.uow.sync_jobs.update(
            job,
            status="queued",
            error_message=None,
            retry_count=job.retry_count,
            retry_after=job.retry_after,
        )
        await self.uow.commit()
        return {"job_id": job_id, "status": "retried", "retry_count": job.retry_count, "retry_after": job.retry_after.isoformat()}

    async def get_schedule_status(self, source_id: str) -> dict | None:
        schedules = await self.uow.sync_schedules.get_by_source(source_id)
        if not schedules:
            return None

        schedule = schedules[0]
        return {
            "id": str(schedule.id),
            "source_id": str(schedule.source_id),
            "project_id": str(schedule.project_id),
            "frequency": schedule.frequency,
            "status": schedule.status,
            "last_run_at": schedule.last_run_at.isoformat() if schedule.last_run_at else None,
            "next_run_at": schedule.next_run_at.isoformat() if schedule.next_run_at else None,
            "retry_count": schedule.retry_count,
            "options": schedule.options,
            "created_at": schedule.created_at.isoformat() if schedule.created_at else None,
            "updated_at": schedule.updated_at.isoformat() if schedule.updated_at else None,
        }

    def _calculate_next_run(self, frequency: str, from_time: datetime) -> datetime | None:
        if frequency == "hourly":
            return from_time + timedelta(hours=1)
        elif frequency == "daily":
            return from_time + timedelta(days=1)
        elif frequency == "weekly":
            return from_time + timedelta(weeks=1)
        elif frequency == "manual":
            return None
        elif frequency == "priority":
            return from_time
        elif frequency == "incremental":
            return from_time + timedelta(hours=1)
        return None

    def _backoff_delay(self, retry_count: int) -> int:
        delays = [1, 5, 25]
        if retry_count < len(delays):
            return delays[retry_count]
        return delays[-1]