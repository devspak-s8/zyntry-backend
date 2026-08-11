from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.core import ws_events


@pytest.mark.asyncio
async def test_sync_progress_event_is_sent_only_to_the_requesting_user(monkeypatch) -> None:
    manager = AsyncMock()
    monkeypatch.setattr(ws_events, "_get_manager", lambda: manager)

    await ws_events.emit_knowledge_sync_updated(
        "user-1",
        job_id="job-1",
        source_id="source-1",
        project_id="project-1",
        status="running",
        progress=20,
        current_step="crawling",
    )

    manager.send_to_user.assert_awaited_once_with(
        {
            "type": "knowledge.sync.updated",
            "payload": {
                "job_id": "job-1",
                "source_id": "source-1",
                "project_id": "project-1",
                "status": "running",
                "progress": 20,
                "current_step": "crawling",
                "error_message": None,
                "stats": {},
            },
        },
        "user-1",
    )
