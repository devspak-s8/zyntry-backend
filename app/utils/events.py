from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.core.database import run_async

logger = logging.getLogger(__name__)


def emit_project_event(project_id: str, organization_id: str | None, event_type: str, data: dict | None = None) -> None:
    async def _emit() -> None:
        from app.core.database import async_session_factory
        from app.services.webhooks import EventService, WebhookService

        async with async_session_factory() as session:
            event_service = EventService(session)
            webhook_service = WebhookService(session)
            pid = __import__("uuid").UUID(project_id) if project_id else None
            oid = __import__("uuid").UUID(organization_id) if organization_id else None
            await event_service.emit(event_type, pid, oid, data)
            if pid:
                await webhook_service.deliver_event(event_type, pid, data or {})

    run_async(_emit())
