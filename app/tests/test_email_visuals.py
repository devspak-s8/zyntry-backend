from __future__ import annotations

from pathlib import Path

import pytest
from httpx import AsyncClient

from app.emails import _email_visual_category, build_password_reset, build_project_created


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
