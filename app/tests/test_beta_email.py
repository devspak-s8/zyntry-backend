from __future__ import annotations

from app.emails import EMAIL_TEMPLATES, build_zyntry_beta_invitation


def test_beta_invitation_is_registered() -> None:
    assert EMAIL_TEMPLATES["zyntry_beta_invitation"] is build_zyntry_beta_invitation


def test_beta_invitation_contains_branded_content_and_plain_text() -> None:
    html, text = build_zyntry_beta_invitation(
        access_date="tomorrow",
        recipient_name="Ada",
        app_url="https://staging.zyntry.space",
    )

    assert "FOUNDING BETA" in html
    assert "You're one of the first in." in html
    assert "Check your inbox again tomorrow" in html
    assert 'href="https://staging.zyntry.space"' in html
    assert "Hey Ada" in text
    assert "Nothing is required from you today" in text


def test_beta_invitation_escapes_dynamic_html() -> None:
    html, _ = build_zyntry_beta_invitation(
        access_date="<script>alert(1)</script>",
        recipient_name="<b>Ada</b>",
        app_url='https://example.com/\" onclick=\"alert(1)',
    )

    assert "<script>" not in html
    assert "<b>Ada</b>" not in html
    assert 'onclick="alert(1)' not in html
