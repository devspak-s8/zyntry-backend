from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from app.admin.constants import FeatureFlagType
from app.admin.feature_registry import (
    BETA_FEATURE_KEYS,
    STABLE_FEATURE_KEYS,
    SYSTEM_FEATURES,
    SYSTEM_FEATURES_BY_KEY,
)
from app.admin.services.feature_seeding import seed_system_feature_flags

EXPECTED_STABLE_KEYS = {
    "dashboard",
    "knowledge_bases",
    "ai_models",
    "runtime_management",
    "runtime_console",
    "deployments",
    "api_keys",
    "analytics",
    "billing",
    "credit_purchases",
    "developer_settings",
}

EXPECTED_BETA_KEYS = {
    "knowledge_sources",
    "provider_connections",
    "tools_connectors",
    "model_routing",
    "runtime_assistant_beta",
    "observability",
    "actions",
    "workflows",
    "webhooks",
}


def _result(created: list[str]) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = created
    return result


def test_registry_has_expected_unique_feature_keys() -> None:
    keys = [feature.key for feature in SYSTEM_FEATURES]

    assert len(keys) == len(set(keys))
    assert set(SYSTEM_FEATURES_BY_KEY) == EXPECTED_STABLE_KEYS | EXPECTED_BETA_KEYS
    assert STABLE_FEATURE_KEYS == EXPECTED_STABLE_KEYS
    assert BETA_FEATURE_KEYS == EXPECTED_BETA_KEYS


def test_stable_features_start_globally_enabled() -> None:
    for key in STABLE_FEATURE_KEYS:
        feature = SYSTEM_FEATURES_BY_KEY[key]
        assert feature.enabled is True
        assert feature.default_value is True
        assert feature.rollout_percentage == 100
        assert feature.flag_type is FeatureFlagType.TOGGLE


def test_beta_features_start_allowlist_only() -> None:
    for key in BETA_FEATURE_KEYS:
        feature = SYSTEM_FEATURES_BY_KEY[key]
        assert feature.enabled is True
        assert feature.default_value is False
        assert feature.rollout_percentage == 0
        assert feature.flag_type is FeatureFlagType.PERCENTAGE


def test_registry_does_not_contain_beta_user_data() -> None:
    serialized = repr(SYSTEM_FEATURES).lower()

    assert "@" not in serialized
    assert "gmail" not in serialized


@pytest.mark.asyncio
async def test_seeder_uses_conflict_safe_insert_and_commits() -> None:
    db = AsyncMock()
    db.execute.return_value = _result(["dashboard", "runtime_assistant_beta"])

    created = await seed_system_feature_flags(db)

    assert created == ["dashboard", "runtime_assistant_beta"]
    db.commit.assert_awaited_once()
    statement = db.execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT (key) DO NOTHING" in sql
    assert "RETURNING admin_feature_flags.key" in sql


@pytest.mark.asyncio
async def test_repeated_seed_preserves_existing_records() -> None:
    db = AsyncMock()
    db.execute.side_effect = [_result(["dashboard"]), _result([])]

    first_created = await seed_system_feature_flags(db)
    second_created = await seed_system_feature_flags(db)

    assert first_created == ["dashboard"]
    assert second_created == []
    assert db.execute.await_count == 2
    assert db.commit.await_count == 2
