from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.runtime_assistant.configuration import (
    configuration_change_impact,
    normalize_configuration_changes,
    parse_configuration_change,
)
from app.services.runtime_assistant.planner import RuntimeAssistantPlanner
from app.services.runtime_assistant.schemas import RuntimeContext, ToolDefinition, UserRole
from app.services.runtime_assistant.tools import _update_runtime_configuration
from app.services.model_compatibility import infer_provider_for_model, provider_model_mismatch


def _context() -> RuntimeContext:
    return RuntimeContext(
        runtime_id="runtime",
        project_id="project",
        organization_id="organization",
        user_id="user",
        user_role=UserRole.DEVELOPER,
    )


def test_configuration_read_question_is_not_a_mutation() -> None:
    assert parse_configuration_change("What is the current configuration?") is None


def test_explicit_configuration_change_is_normalized_and_planned_as_write() -> None:
    change = parse_configuration_change(
        "Change the model to gemini-2.5-flash and set temperature to 0.3"
    )
    assert change == {
        "model": "gemini-2.5-flash",
        "config": {"temperature": 0.3},
    }

    planner = RuntimeAssistantPlanner(
        _context(),
        [
            ToolDefinition(
                name="update_runtime_configuration",
                description="Update runtime configuration",
                required_permission=UserRole.DEVELOPER,
                action_type="write",
            )
        ],
    )
    plan = planner.plan("Change the model to gemini-2.5-flash")
    assert len(plan.tool_calls) == 1
    assert plan.tool_calls[0].name == "update_runtime_configuration"
    assert plan.tool_calls[0].arguments == {"changes": {"model": "gemini-2.5-flash"}}


def test_configuration_values_are_validated_before_proposal() -> None:
    with pytest.raises(ValueError, match="temperature must be between 0 and 2"):
        normalize_configuration_changes({"config": {"temperature": 2.1}})

    with pytest.raises(ValueError, match="Unsupported runtime configuration field"):
        normalize_configuration_changes({"status": "active"})


def test_invalid_configuration_request_is_reported_without_a_mutation() -> None:
    planner = RuntimeAssistantPlanner(
        _context(),
        [
            ToolDefinition(
                name="update_runtime_configuration",
                description="Update runtime configuration",
                required_permission=UserRole.DEVELOPER,
                action_type="write",
            )
        ],
    )
    plan = planner.plan("Set temperature to 3")
    assert plan.tool_calls == []
    assert plan.configuration_error == "temperature must be between 0 and 2"


def test_parser_supports_multiple_changes_and_fallback_models() -> None:
    assert parse_configuration_change(
        "Set fallback models to gpt-4o-mini, gpt-4o and set cache ttl to 60"
    ) == {
        "fallback_models": ["gpt-4o-mini", "gpt-4o"],
        "config": {"cache_ttl_seconds": 60},
    }


def test_automatic_model_routing_maps_to_dynamic_routing_flag() -> None:
    assert parse_configuration_change(
        "Configure it to automatically route the models"
    ) == {"config": {"dynamic_routing_enabled": True}}
    assert parse_configuration_change(
        "Disable automatic model routing"
    ) == {"config": {"dynamic_routing_enabled": False}}
    assert parse_configuration_change(
        "No, change it to automatic"
    ) == {"config": {"dynamic_routing_enabled": True}}
    assert parse_configuration_change(
        "Now I want to switch to automatc"
    ) == {"config": {"dynamic_routing_enabled": True}}


def test_automatic_routing_alias_is_canonicalized() -> None:
    assert normalize_configuration_changes(
        {"routing_strategy": "automatic_model_routing"}
    ) == {"config": {"dynamic_routing_enabled": True}}


def test_model_provider_compatibility_is_checked_without_blocking_custom_models() -> None:
    assert infer_provider_for_model("gemini-2.5-flash") == "google"
    assert provider_model_mismatch("openai", "gemini-2.5-flash")
    assert provider_model_mismatch("google", "gemini-2.5-flash") is None
    assert provider_model_mismatch("openai", "my-private-model") is None


def test_rebuild_is_a_separate_confirmed_action() -> None:
    planner = RuntimeAssistantPlanner(
        _context(),
        [
            ToolDefinition(
                name="rebuild_embeddings",
                description="Rebuild runtime embeddings",
                required_permission=UserRole.DEVELOPER,
                action_type="execute",
            )
        ],
    )
    plan = planner.plan("Rebuild the runtime")
    assert len(plan.tool_calls) == 1
    assert plan.tool_calls[0].name == "rebuild_embeddings"

    short_plan = planner.plan("rebuild")
    assert len(short_plan.tool_calls) == 1
    assert short_plan.tool_calls[0].name == "rebuild_embeddings"


def test_completion_question_checks_current_config_and_deployment() -> None:
    planner = RuntimeAssistantPlanner(
        _context(),
        [
            ToolDefinition(
                name="get_runtime_config",
                description="Get current runtime configuration",
                required_permission=UserRole.VIEWER,
                action_type="read",
            ),
            ToolDefinition(
                name="get_deployment_status",
                description="Get deployment status",
                required_permission=UserRole.VIEWER,
                action_type="read",
            ),
        ],
    )
    plan = planner.plan("Are you done?")
    assert [call.name for call in plan.tool_calls] == [
        "get_runtime_config",
        "get_deployment_status",
    ]


def test_configuration_impact_marks_index_changes_for_rebuild() -> None:
    impact = configuration_change_impact(
        {"model": "gpt-4o-mini", "config": {"temperature": 0.2}}
    )
    assert impact["changed_fields"] == ["model", "config.temperature"]
    assert impact["requires_rebuild"] is True
    assert impact["rebuild_fields"] == ["model"]


@pytest.mark.asyncio
async def test_confirmed_configuration_update_merges_config_and_reports_impact() -> None:
    runtime_service = SimpleNamespace(
        get=AsyncMock(
            return_value={
                "id": "runtime",
                "model": "gpt-4o",
                "chunk_size": 512,
                "chunk_overlap": 64,
                "config": {"temperature": 0.7, "cache_enabled": True},
            }
        ),
        update=AsyncMock(return_value={"id": "runtime", "model": "gemini-2.5-flash"}),
    )
    assistant_tools = SimpleNamespace(
        runtime_id="runtime",
        runtime_service=runtime_service,
    )

    result = await _update_runtime_configuration(
        assistant_tools,
        {"model": "gemini-2.5-flash", "config": {"temperature": 0.3}},
    )

    update_data = runtime_service.update.await_args.args[1]
    assert update_data.model == "gemini-2.5-flash"
    assert update_data.config == {"temperature": 0.3, "cache_enabled": True}
    assert result["status"] == "success"
    assert result["requires_rebuild"] is True
    assert result["changed_fields"] == ["model", "config.temperature"]
