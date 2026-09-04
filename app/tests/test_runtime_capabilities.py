from __future__ import annotations

from types import SimpleNamespace

from app.schemas.capabilities import CrossSourceJoinRequest, EvaluationCase
from app.services.runtime_capabilities import (
    default_access_policy,
    evaluate_case,
    join_source_records,
    normalize_access_policy,
    resolve_role,
)


def test_default_access_policy_is_read_first_and_write_restricted():
    policy = default_access_policy()
    assert policy["default_role"] == "developer"
    assert policy["roles"]["developer"]["can_invoke"] is True
    assert policy["roles"]["developer"]["can_write"] is False


def test_access_policy_normalization_keeps_custom_source_allowlist():
    policy = normalize_access_policy({"roles": {"student": {"allowed_sources": ["Postgres", "docs"]}}})
    assert policy["roles"]["student"]["allowed_sources"] == ["docs", "postgres"]


def test_cross_source_join_retains_provenance_and_matches_on_key():
    result = join_source_records(CrossSourceJoinRequest(sources=[
        {"source": "postgres", "records": [{"student_id": "s1", "grade": 90}]},
        {"source": "documents", "records": [{"student_id": "s1", "note": "excellent"}]},
    ], join_on="student_id"))
    assert result["matched_records"] == 1
    assert result["records"][0]["postgres"]["grade"] == 90
    assert result["provenance"][0]["source"] == "postgres"


def test_evaluation_case_scores_expected_terms_and_citations():
    case = EvaluationCase(name="citation", input="What is it?", expected_contains=["answer"], expected_citations=True)
    result = evaluate_case(case, "The answer is here: https://example.com")
    assert result.passed is True
    assert result.score == 1.0


def test_role_is_resolved_from_user_settings():
    user = SimpleNamespace(is_superuser=False, settings={"role": "Instructor"})
    assert resolve_role(user) == "instructor"
