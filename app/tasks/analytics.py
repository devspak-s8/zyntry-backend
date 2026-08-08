from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from app.core.database import run_async
from app.core.logging import get_logger
from app.workers.celery_app import celery_app

logger = get_logger("app.tasks.analytics")


@celery_app.task(name="app.tasks.analytics.generate_usage_report")
def generate_usage_report_task(
    project_id: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    async def _run() -> dict[str, Any]:
        from app.core.database import async_session_factory
        from app.models.projects import Project
        from app.models.runtimes import Runtime
        from app.models.knowledge import Document
        from sqlalchemy import func, select

        async with async_session_factory() as db:
            end = datetime.fromisoformat(end_date) if end_date else datetime.now(UTC)
            start = datetime.fromisoformat(start_date) if start_date else end - timedelta(days=30)

            result: dict[str, Any] = {}

            runtime_count_r = await db.execute(
                select(func.count()).select_from(Runtime).where(Runtime.project_id == uuid.UUID(project_id))
            )
            result["runtime_count"] = runtime_count_r.scalar() or 0

            doc_count_r = await db.execute(
                select(func.count()).select_from(Document).where(Document.knowledge_base_id.in_(
                    select(Project.id).where(Project.id == uuid.UUID(project_id))
                ))
            )
            result["document_count"] = doc_count_r.scalar() or 0

            token_usage_r = await db.execute(
                select(
                    func.sum(UsageLog.input_tokens).label("input_tokens"),
                    func.sum(UsageLog.output_tokens).label("output_tokens"),
                    func.sum(UsageLog.embedding_tokens).label("embedding_tokens"),
                )
                .where(
                    UsageLog.project_id == uuid.UUID(project_id),
                    UsageLog.created_at >= start,
                    UsageLog.created_at <= end,
                )
            )
            row = token_usage_r.one()
            result["total_input_tokens"] = int(row.input_tokens or 0)
            result["total_output_tokens"] = int(row.output_tokens or 0)
            result["total_embedding_tokens"] = int(row.embedding_tokens or 0)

            result["period_start"] = start.isoformat()
            result["period_end"] = end.isoformat()
            return result

    from app.models.billing import UsageLog
    return run_async(_run())


@celery_app.task(name="app.tasks.analytics.track_usage_event")
def track_usage_event_task(
    project_id: str,
    metric: str,
    quantity: int = 1,
    model: str | None = None,
    provider: str | None = None,
    runtime_id: str | None = None,
    user_id: str | None = None,
    cost: Decimal | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    async def _run() -> str:
        from app.core.database import async_session_factory
        from app.models.billing import UsageLog
        from decimal import Decimal as Dec

        async with async_session_factory() as db:
            event = UsageLog(
                user_id=uuid.UUID(user_id) if user_id else None,
                project_id=uuid.UUID(project_id),
                runtime_id=uuid.UUID(runtime_id) if runtime_id else None,
                provider=provider or "unknown",
                model=model or "unknown",
                operation=metric,
                input_tokens=quantity if metric == "input_tokens" else 0,
                output_tokens=quantity if metric == "output_tokens" else 0,
                embedding_tokens=quantity if metric == "embedding_tokens" else 0,
                vector_searches=quantity if metric == "vector_search" else 0,
                storage_bytes=quantity if metric == "storage_bytes" else 0,
                requests=quantity if metric == "request" else 1,
                latency_ms=None,
                cost=cost if cost else Dec("0.0000"),
                metadata_=metadata or {},
            )
            db.add(event)
            await db.commit()
            return str(event.id)

    return run_async(_run())


@celery_app.task(name="app.tasks.analytics.generate_provider_usage")
def generate_provider_usage_task(
    organization_id: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    async def _run() -> dict[str, Any]:
        from app.core.database import async_session_factory
        from app.models.billing import UsageLog
        from app.models.projects import Project
        from sqlalchemy import func, select

        async with async_session_factory() as db:
            end = datetime.fromisoformat(end_date) if end_date else datetime.now(UTC)
            start = datetime.fromisoformat(start_date) if start_date else end - timedelta(days=30)

            result = await db.execute(
                select(
                    UsageLog.provider,
                    UsageLog.model,
                    func.sum(UsageLog.input_tokens).label("input_tokens"),
                    func.sum(UsageLog.output_tokens).label("output_tokens"),
                    func.sum(UsageLog.requests).label("total_requests"),
                    func.sum(UsageLog.cost).label("total_cost"),
                )
                .join(Project, Project.id == UsageLog.project_id)
                .where(
                    Project.organization_id == uuid.UUID(organization_id),
                    UsageLog.created_at >= start,
                    UsageLog.created_at <= end,
                )
                .group_by(UsageLog.provider, UsageLog.model)
                .order_by(func.sum(UsageLog.cost).desc())
            )
            rows = result.all()
            return {
                "organization_id": organization_id,
                "period_start": start.isoformat(),
                "period_end": end.isoformat(),
                "providers": [
                    {
                        "provider": r[0],
                        "model": r[1],
                        "input_tokens": int(r[2] or 0),
                        "output_tokens": int(r[3] or 0),
                        "total_requests": int(r[4] or 0),
                        "total_cost": float(r[5] or 0),
                    }
                    for r in rows
                ],
            }

    return run_async(_run())


@celery_app.task(name="app.tasks.analytics.generate_cost_report")
def generate_cost_report_task(
    organization_id: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    async def _run() -> dict[str, Any]:
        from app.core.database import async_session_factory
        from app.models.billing import UsageLog
        from app.models.projects import Project
        from sqlalchemy import func, select

        async with async_session_factory() as db:
            end = datetime.fromisoformat(end_date) if end_date else datetime.now(UTC)
            start = datetime.fromisoformat(start_date) if start_date else end - timedelta(days=30)

            total_cost_r = await db.execute(
                select(func.sum(UsageLog.cost))
                .join(Project, Project.id == UsageLog.project_id)
                .where(
                    Project.organization_id == uuid.UUID(organization_id),
                    UsageLog.created_at >= start,
                    UsageLog.created_at <= end,
                )
            )
            total_cost = Decimal(total_cost_r.scalar() or 0)

            model_cost_r = await db.execute(
                select(
                    UsageLog.provider,
                    UsageLog.model,
                    func.sum(UsageLog.cost).label("model_cost"),
                    func.sum(UsageLog.input_tokens).label("input_tokens"),
                    func.sum(UsageLog.output_tokens).label("output_tokens"),
                )
                .join(Project, Project.id == UsageLog.project_id)
                .where(
                    Project.organization_id == uuid.UUID(organization_id),
                    UsageLog.created_at >= start,
                    UsageLog.created_at <= end,
                )
                .group_by(UsageLog.provider, UsageLog.model)
                .order_by(func.sum(UsageLog.cost).desc())
            )
            model_costs = [
                {
                    "provider": r[0],
                    "model": r[1],
                    "cost": float(r[2] or 0),
                    "input_tokens": int(r[3] or 0),
                    "output_tokens": int(r[4] or 0),
                }
                for r in model_cost_r.all()
            ]

            return {
                "organization_id": organization_id,
                "period_start": start.isoformat(),
                "period_end": end.isoformat(),
                "total_cost": float(total_cost),
                "by_model": model_costs,
            }

    return run_async(_run())


@celery_app.task(name="app.tasks.analytics.generate_runtime_stats")
def generate_runtime_stats_task(
    runtime_id: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    async def _run() -> dict[str, Any]:
        from app.core.database import async_session_factory
        from app.models.billing import UsageLog
        from sqlalchemy import func, select

        async with async_session_factory() as db:
            end = datetime.fromisoformat(end_date) if end_date else datetime.now(UTC)
            start = datetime.fromisoformat(start_date) if start_date else end - timedelta(days=30)

            stats_result = await db.execute(
                select(
                    func.sum(UsageLog.requests).label("total_requests"),
                    func.avg(UsageLog.latency_ms).label("avg_latency_ms"),
                    func.sum(UsageLog.input_tokens).label("input_tokens"),
                    func.sum(UsageLog.output_tokens).label("output_tokens"),
                    func.sum(UsageLog.cost).label("total_cost"),
                )
                .where(
                    UsageLog.runtime_id == uuid.UUID(runtime_id),
                    UsageLog.created_at >= start,
                    UsageLog.created_at <= end,
                )
            )
            row = stats_result.one()

            return {
                "runtime_id": runtime_id,
                "period_start": start.isoformat(),
                "period_end": end.isoformat(),
                "total_requests": int(row.total_requests or 0),
                "avg_response_time_ms": float(row.avg_latency_ms or 0),
                "total_input_tokens": int(row.input_tokens or 0),
                "total_output_tokens": int(row.output_tokens or 0),
                "total_cost": float(row.total_cost or 0),
            }

    return run_async(_run())
