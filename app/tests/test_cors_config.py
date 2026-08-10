from app.main import _parse_cors_origins


def test_parse_cors_origins_supports_environment_specific_frontends() -> None:
    origins = _parse_cors_origins(
        "https://staging.zyntry.space, https://zyntry.space,"
        "http://localhost:5173"
    )

    assert origins == [
        "https://staging.zyntry.space",
        "https://zyntry.space",
        "http://localhost:5173",
    ]


def test_parse_cors_origins_ignores_empty_entries() -> None:
    assert _parse_cors_origins(" ,https://staging.zyntry.space,, ") == [
        "https://staging.zyntry.space"
    ]
