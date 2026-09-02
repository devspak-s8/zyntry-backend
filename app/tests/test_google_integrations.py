from __future__ import annotations

import pytest

from app.services.actions.registry import ActionRegistry
from app.services.connectors import registry as connector_registry
from app.services.connectors.google_services import GoogleSheetsConnector
from app.services.integrations.definitions import integration_registry
from app.services.onboarding.models import FastOnboardingModelProvider


GOOGLE_SLUGS = {
    "google_people",
    "google_sheets",
    "google_docs",
    "google_chat",
    "google_meet",
    "google_forms",
    "bigquery",
    "google_cloud_storage",
    "firestore",
    "google_analytics",
    "google_logging",
    "google_monitoring",
}


def test_google_catalog_entries_have_inputs_and_read_write_metadata() -> None:
    definitions = {item.slug: item for item in integration_registry.list_all()}
    assert GOOGLE_SLUGS <= definitions.keys()
    for slug in GOOGLE_SLUGS:
        definition = definitions[slug]
        assert definition.status in {"available", "beta"}
        assert definition.configuration_schema["read_only_default"] is True
        assert definition.configuration_schema["input_fields"]
        assert any(not capability.is_write for capability in definition.capabilities)

    assert any(
        capability.is_write
        for capability in definitions["google_sheets"].capabilities
    )
    assert any(
        capability.is_write
        for capability in definitions["firestore"].capabilities
    )


def test_google_connectors_are_registered() -> None:
    supported = set(connector_registry.list_supported())
    assert GOOGLE_SLUGS <= supported


def test_google_actions_are_registered_and_writes_are_guarded() -> None:
    for provider in GOOGLE_SLUGS:
        actions = ActionRegistry.list_actions(provider)
        assert actions
        assert all(action.provider == provider for action in actions)

    sheets_actions = {action.name: action for action in ActionRegistry.list_actions("google_sheets")}
    assert sheets_actions["read_ranges"].required_permissions == []
    assert sheets_actions["update_cells"].required_permissions == ["write"]
    assert sheets_actions["update_cells"].risk == "medium"


@pytest.mark.asyncio
async def test_google_action_provider_requires_confirmation_for_writes() -> None:
    provider_cls = ActionRegistry.get_provider("google_sheets")
    assert provider_cls is not None
    provider = provider_cls(credentials={"access_token": "test-token"})
    response = await provider.execute(
        "update_cells",
        {"spreadsheet_id": "sheet", "range": "Sheet1!A1", "values": [["x"]]},
        {"confirmed": False},
    )
    assert response.success is False
    assert response.requires_confirmation is True


@pytest.mark.asyncio
async def test_google_connector_reports_missing_resource_configuration() -> None:
    connector = GoogleSheetsConnector(
        project_id="project",
        source_id="source",
        config={},
        credentials={"access_token": "test-token"},
    )
    result = await connector.test()
    assert result["success"] is False
    assert "spreadsheet_id" in result["message"]


def test_onboarding_detects_google_services() -> None:
    provider = FastOnboardingModelProvider()
    detected = provider._detect_integrations(
        "Use Google Sheets, Google Docs, BigQuery, Google Chat and Cloud Monitoring"
    )
    assert {"google_sheets", "google_docs", "bigquery", "google_chat", "google_monitoring"} <= set(detected)
