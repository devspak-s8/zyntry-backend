from app.core.config import AppSettings


def test_production_security_headers_have_a_frontend_origin() -> None:
    settings = AppSettings(
        APP_ENV="production",
        APP_DEBUG=False,
        APP_URL="https://api.zyntry.space",
        FRONTEND_URL="https://zyntry.space",
    )

    assert settings.FRONTEND_URL == "https://zyntry.space"
