from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.admin.constants import FeatureFlagType
from app.admin.models import FeatureFlag
from app.admin.schemas import FeatureFlagCreate
from app.admin.services.feature_flags import evaluate_feature_flag


def _flag(**overrides) -> FeatureFlag:
    values = {
        "key": "runtime_assistant_v2",
        "name": "Runtime Assistant v2",
        "scope": "runtime",
        "flag_type": FeatureFlagType.PERCENTAGE,
        "enabled": True,
        "default_value": False,
        "rollout_percentage": 0,
        "allowlist": [],
        "is_system": False,
    }
    values.update(overrides)
    return FeatureFlag(**values)


def _evaluate(
    flag: FeatureFlag, *, user_id: uuid.UUID, org_id: uuid.UUID | None, email: str
) -> bool:
    return evaluate_feature_flag(
        flag,
        user_id=user_id,
        organization_id=org_id,
        email=email,
    )


def test_disabled_flag_is_always_off() -> None:
    user_id = uuid.uuid4()
    flag = _flag(enabled=False, rollout_percentage=100, allowlist=[f"user:{user_id}"])

    assert not _evaluate(flag, user_id=user_id, org_id=None, email="beta@example.com")


@pytest.mark.parametrize("target_kind", ["user", "org", "email"])
def test_allowlist_enables_selected_beta_tester(target_kind: str) -> None:
    user_id = uuid.uuid4()
    org_id = uuid.uuid4()
    email = "Beta@Example.com"
    identifiers = {"user": user_id, "org": org_id, "email": email.lower()}
    flag = _flag(allowlist=[f"{target_kind}:{identifiers[target_kind]}"])

    assert _evaluate(flag, user_id=user_id, org_id=org_id, email=email)


def test_toggle_uses_default_value_for_non_allowlisted_users() -> None:
    flag = _flag(flag_type=FeatureFlagType.TOGGLE, default_value=True)

    assert _evaluate(flag, user_id=uuid.uuid4(), org_id=None, email="user@example.com")


def test_percentage_boundaries() -> None:
    user_id = uuid.uuid4()
    org_id = uuid.uuid4()

    assert not _evaluate(
        _flag(rollout_percentage=0),
        user_id=user_id,
        org_id=org_id,
        email="user@example.com",
    )
    assert _evaluate(
        _flag(rollout_percentage=100),
        user_id=user_id,
        org_id=org_id,
        email="user@example.com",
    )


def test_percentage_is_consistent_for_an_organization() -> None:
    flag = _flag(rollout_percentage=50)
    org_id = uuid.uuid4()

    results = {
        _evaluate(flag, user_id=uuid.uuid4(), org_id=org_id, email=f"user{i}@example.com")
        for i in range(10)
    }

    assert len(results) == 1


def test_feature_flag_schema_normalizes_and_deduplicates_allowlist() -> None:
    user_id = uuid.uuid4()
    body = FeatureFlagCreate(
        key="new_provider_router",
        name="New provider router",
        allowlist=[f"USER:{user_id}", f"user:{user_id}", "email:BETA@EXAMPLE.COM"],
    )

    assert body.allowlist == [f"user:{user_id}", "email:beta@example.com"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("key", "Bad Key"),
        ("rollout_percentage", 101),
        ("allowlist", ["plain-user-id"]),
        ("allowlist", ["org:not-a-uuid"]),
    ],
)
def test_feature_flag_schema_rejects_invalid_configuration(field: str, value: object) -> None:
    data = {"key": "valid_flag", "name": "Valid flag", field: value}

    with pytest.raises(ValidationError):
        FeatureFlagCreate(**data)
