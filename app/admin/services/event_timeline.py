from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.models import AdminEventTimeline
from app.admin.repositories import AdminEventTimelineRepository
from app.models.billing import UsageLog
from app.models.runtimes import Runtime


class EventTimelineService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._repo = AdminEventTimelineRepository(db)

    async def create_event(
        self,
        request_id: str,
        event_type: str,
        title: str,
        description: str | None,
        sequence: int,
        organization_id: str | None,
        user_id: str | None,
        api_key_id: str | None,
        runtime_id: str | None,
        ip_address: str | None,
        provider: str | None,
        model: str | None,
        latency_ms: int | None,
        status_code: int | None,
        cost: float | None,
        data: dict[str, Any] | None,
    ) -> AdminEventTimeline:
        event = AdminEventTimeline(
            request_id=request_id,
            event_type=event_type,
            title=title,
            description=description,
            sequence=sequence,
            organization_id=organization_id,
            user_id=user_id,
            api_key_id=api_key_id,
            runtime_id=runtime_id,
            ip_address=ip_address,
            provider=provider,
            model=model,
            latency_ms=latency_ms,
            status_code=status_code,
            cost=cost,
            data=data,
        )
        self.db.add(event)
        await self.db.flush()
        from app.admin.websocket_manager import admin_ws_manager

        await admin_ws_manager.broadcast(
            {
                "type": "invocation",
                "event": {
                    "id": str(event.id),
                    "request_id": event.request_id,
                    "event_type": event.event_type,
                    "title": event.title,
                    "description": event.description,
                    "sequence": event.sequence,
                    "timestamp": event.created_at.isoformat() if event.created_at else "",
                    "organization_id": str(event.organization_id) if event.organization_id else None,
                    "runtime_id": str(event.runtime_id) if event.runtime_id else None,
                    "provider": event.provider,
                    "model": event.model,
                    "latency_ms": event.latency_ms,
                    "status_code": event.status_code,
                    "cost": float(event.cost) if event.cost else None,
                    "data": event.data,
                },
            }
        )
        return event

    async def get_request_timeline(self, request_id: str) -> list[AdminEventTimeline]:
        return await self._repo.list_by_request_id(request_id)

    async def get_request_replay(self, request_id: str) -> dict[str, Any] | None:
        timeline = await self.get_request_timeline(request_id)
        if not timeline:
            return None

        runtime_id = timeline[0].runtime_id
        user_id = timeline[0].user_id
        org_id = timeline[0].organization_id

        first_event = timeline[0]

        usage = None
        if first_event.model:
            usage_result = await self.db.execute(
                select(UsageLog).where(UsageLog.request_id == request_id)
            )
            usage_row = usage_result.scalar_one_or_none()
            if usage_row:
                usage = {
                    "input_tokens": usage_row.input_tokens,
                    "output_tokens": usage_row.output_tokens,
                    "cost": float(usage_row.cost) if usage_row.cost else 0,
                    "latency_ms": usage_row.latency_ms,
                }

        runtime_data = None
        if runtime_id:
            runtime_result = await self.db.execute(select(Runtime).where(Runtime.id == runtime_id))
            runtime = runtime_result.scalar_one_or_none()
            if runtime:
                runtime_data = {
                    "name": runtime.name,
                    "provider": runtime.provider,
                    "model": runtime.model,
                    "status": runtime.status,
                }

        return {
            "request_id": request_id,
            "timeline": [
                {
                    "id": str(e.id) if e.id else None,
                    "event_type": e.event_type,
                    "title": e.title,
                    "description": e.description,
                    "sequence": e.sequence,
                    "timestamp": e.created_at.isoformat() if e.created_at else "",
                    "organization_id": str(e.organization_id) if e.organization_id else None,
                    "user_id": str(e.user_id) if e.user_id else None,
                    "runtime_id": str(e.runtime_id) if e.runtime_id else None,
                    "provider": e.provider,
                    "model": e.model,
                    "latency_ms": e.latency_ms,
                    "status_code": e.status_code,
                    "cost": float(e.cost) if e.cost else None,
                    "data": e.data,
                }
                for e in timeline
            ],
            "runtime_id": runtime_id,
            "user_id": user_id,
            "org_id": org_id,
            "usage": usage,
            "runtime_data": runtime_data,
        }

    async def list_events(
        self,
        limit: int = 50,
        offset: int = 0,
        organization_id: str | None = None,
        user_id: str | None = None,
        runtime_id: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        event_type: str | None = None,
    ) -> list[AdminEventTimeline]:
        def parse_uuid(value: str | None) -> uuid.UUID | None:
            if not value:
                return None
            try:
                return uuid.UUID(value)
            except ValueError:
                return None

        return await self._repo.list_all(
            limit=limit,
            offset=offset,
            organization_id=parse_uuid(organization_id),
            user_id=parse_uuid(user_id),
            runtime_id=parse_uuid(runtime_id),
            date_from=date_from,
            date_to=date_to,
            event_type=event_type,
        )
