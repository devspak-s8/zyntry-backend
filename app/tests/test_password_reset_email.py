from app.emails import build_password_reset


def test_password_reset_email_contains_code_and_current_expiry() -> None:
    html, text = build_password_reset("Test User", "AB12CD")

    assert "AB12CD" in html
    assert "AB12CD" in text
    assert "15 minutes" in html
    assert "15 minutes" in text
    assert "?token=" not in html
    assert "?token=" not in text
