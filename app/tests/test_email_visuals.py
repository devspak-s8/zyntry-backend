from __future__ import annotations

from pathlib import Path

import pytest
from httpx import AsyncClient

from app.emails import (
    EMAIL_TEMPLATES,
    _email_visual_category,
    build_password_reset,
    build_project_created,
)
from app.services.notifications import _EMAIL_TEMPLATE_MAP
from app.events import EventType


@pytest.mark.parametrize(
    ("name", "title", "expected"),
    [
        ("auth.password_reset", "Reset your password", "security"),
        ("billing.payment_success", "Payment successful", "billing"),
        ("source.sync_completed", "Source synchronization completed", "knowledge"),
        ("notification.incident", "Service incident", "operations"),
        ("project.created", "Project created successfully", "platform"),
    ],
)
def test_email_visual_category_mapping(name: str, title: str, expected: str) -> None:
    assert _email_visual_category(name, title) == expected


def test_email_html_contains_logo_and_relevant_visual() -> None:
    security_html, _ = build_password_reset("Test User", "AB12CD")
    project_html, _ = build_project_created("Test User", "Demo Project")

    assert "/zyntry-logo.jpeg" in security_html
    assert "/security.png" in security_html
    assert "/zyntry-logo.jpeg" in project_html
    assert "/platform.png" in project_html
    assert 'background-image:url(' in project_html
    assert '<td background="' in project_html


def test_every_notification_event_has_a_registered_email_template() -> None:
    event_types = [
        value
        for name, value in vars(EventType).items()
        if name.isupper() and isinstance(value, str)
    ]
    missing_mappings = [event_type for event_type in event_types if event_type not in _EMAIL_TEMPLATE_MAP]
    missing_templates = [
        template
        for template in _EMAIL_TEMPLATE_MAP.values()
        if template not in EMAIL_TEMPLATES
    ]

    assert missing_mappings == []
    assert missing_templates == []


def test_password_changed_accepts_event_payload() -> None:
    html, text = EMAIL_TEMPLATES[_EMAIL_TEMPLATE_MAP["auth.password_changed"]](
        user_name="Test User"
    )

    assert "Test User" in html
    assert "Password changed successfully" in text


def test_credits_low_accepts_event_payload() -> None:
    html, text = EMAIL_TEMPLATES[_EMAIL_TEMPLATE_MAP["billing.credits_low"]](
        balance="$2.00",
        threshold="$5.00",
    )

    assert "$2.00" in html
    assert "$5.00" in text


def test_all_email_visual_assets_are_packaged() -> None:
    asset_dir = Path(__file__).parents[1] / "static" / "email"
    expected = {
        "zyntry-logo.jpeg",
        "security.png",
        "billing.png",
        "knowledge.png",
        "operations.png",
        "platform.png",
    }

    assert expected == {path.name for path in asset_dir.iterdir() if path.is_file()}


@pytest.mark.asyncio
async def test_email_visual_asset_is_publicly_served(client: AsyncClient) -> None:
    response = await client.get("/static/email/security.png")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG")
