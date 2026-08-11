from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.api.v1.projects import router as projects_router
from app.emails import build_project_created
from app.events import NotificationEvent


def test_project_created_email_template_renders() -> None:
    html, text = build_project_created("Test User", "Demo Project")

    assert "Project created successfully" in html
    assert "Demo Project" in html
    assert "Demo Project" in text


@pytest.mark.asyncio
async def test_project_created_email_delivery_is_awaited(monkeypatch) -> None:
    publish = AsyncMock(return_value={"email": {"success": True}})
    monkeypatch.setattr(projects_router, "publish_notification", publish)
    event = NotificationEvent(
        event_type="project.created",
        recipient="user@example.com",
        data={"user_name": "User", "project_name": "Demo"},
    )

    delivered = await projects_router._deliver_project_created_email(event, uuid4())

    assert delivered is True
    publish.assert_awaited_once_with(event)


@pytest.mark.asyncio
async def test_project_created_email_failure_is_reported(monkeypatch, caplog) -> None:
    publish = AsyncMock(return_value={"email": {"success": False, "error": "rejected"}})
    monkeypatch.setattr(projects_router, "publish_notification", publish)
    event = NotificationEvent("project.created", "user@example.com", {"project_name": "Demo"})

    delivered = await projects_router._deliver_project_created_email(event, uuid4())

    assert delivered is False
    assert "Project created email delivery failed" in caplog.text
