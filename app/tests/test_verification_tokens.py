from app.core.security import (
    generate_verification_token,
    verification_token_candidates,
)


def test_verification_tokens_match_uppercase_ui_format() -> None:
    for _ in range(25):
        token = generate_verification_token()
        assert len(token) == 6
        assert token.isalnum()
        assert token == token.upper()


def test_verification_token_candidates_trim_and_normalize_input() -> None:
    assert verification_token_candidates("  aB3xY9  ") == ("aB3xY9", "AB3XY9")


def test_canonical_verification_token_has_one_candidate() -> None:
    assert verification_token_candidates("AB3XY9") == ("AB3XY9",)
