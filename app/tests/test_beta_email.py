from __future__ import annotations

from app.emails import EMAIL_TEMPLATES, build_zyntry_beta_invitation


def test_beta_invitation_is_registered() -> None:
    assert EMAIL_TEMPLATES["zyntry_beta_invitation"] is build_zyntry_beta_invitation


def test_beta_invitation_contains_branded_content_and_plain_text() -> None:
    html, text = build_zyntry_beta_invitation(
        access_date="today",
        recipient_name="Ada",
        app_url="https://staging.zyntry.space",
        credit_amount="$5.00",
    )

    assert "EARLY ACCESS" in html
    assert "Your Zyntry beta access is ready." in html
    assert "$5.00 is now in your wallet" in html
    assert 'href="https://staging.zyntry.space"' in html
    assert "Hey Ada" in text
    assert "We added $5.00 in testing credit" in text
    assert "linear-gradient" not in html
    assert "—" not in html


def test_beta_invitation_escapes_dynamic_html() -> None:
    html, _ = build_zyntry_beta_invitation(
        access_date="<script>alert(1)</script>",
        recipient_name="<b>Ada</b>",
        app_url='https://example.com/" onclick="alert(1)',
    )

    assert "<script>" not in html
    assert "<b>Ada</b>" not in html
    assert 'onclick="alert(1)' not in html
