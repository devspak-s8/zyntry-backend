from app.core.errors import safe_http_detail


def test_safe_http_detail_preserves_a_user_facing_validation_message() -> None:
    assert safe_http_detail(422, "Name is required") == "Name is required"


def test_safe_http_detail_redacts_driver_and_traceback_text() -> None:
    detail = "sqlalchemy.exc.OperationalError: connection refused"
    assert safe_http_detail(400, detail) == "Please review the request and try again."
    assert safe_http_detail(500, detail) == "A temporary service issue occurred. Please try again shortly."


def test_safe_http_detail_keeps_safe_structured_policy_fields() -> None:
    result = safe_http_detail(
        400,
        {
            "code": "guardrail_blocked",
            "message": "This request was blocked by the runtime safety policy.",
            "guardrail_violations": ["prompt_injection"],
            "debug": "sqlalchemy traceback",
        },
    )
    assert result == {
        "code": "guardrail_blocked",
        "message": "This request was blocked by the runtime safety policy.",
        "guardrail_violations": ["prompt_injection"],
    }


def test_safe_http_detail_preserves_safe_provider_contract_on_server_error() -> None:
    result = safe_http_detail(
        503,
        {
            "code": "onboarding_provider_rate_limited",
            "message": "The onboarding assistant is temporarily busy. Please try again shortly.",
            "retryable": True,
            "action": "retry",
        },
    )
    assert result == {
        "code": "onboarding_provider_rate_limited",
        "message": "The onboarding assistant is temporarily busy. Please try again shortly.",
        "retryable": True,
        "action": "retry",
    }
