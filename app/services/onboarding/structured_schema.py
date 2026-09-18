"""Provider response schemas used by the onboarding model.

Gemini's ``responseSchema`` is an OpenAPI-shaped schema rather than a JSON
Schema document.  Keeping the schema explicit and small avoids sending
Pydantic's ``$defs``/``$ref`` graph to the provider, which Gemini does not
support consistently across model versions.
"""

from __future__ import annotations

from typing import Any


def _string(*, nullable: bool = False, enum: list[str] | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {"type": "STRING"}
    if nullable:
        value["nullable"] = True
    if enum:
        value["enum"] = enum
    return value


def _boolean(*, nullable: bool = False) -> dict[str, Any]:
    value: dict[str, Any] = {"type": "BOOLEAN"}
    if nullable:
        value["nullable"] = True
    return value


def _number() -> dict[str, Any]:
    return {"type": "NUMBER"}


def _string_array() -> dict[str, Any]:
    return {"type": "ARRAY", "items": _string()}


def _integration_requirement_schema() -> dict[str, Any]:
    return {
        "type": "OBJECT",
        "properties": {
            "slug": _string(),
            "purpose": _string(),
            "ownership": _string(
                nullable=True,
                enum=["company", "end_user", "hybrid"],
            ),
            "capabilities": _string_array(),
            "write_access": _boolean(),
            "required": _boolean(),
        },
        "required": ["slug", "purpose", "capabilities", "write_access", "required"],
    }


def _integration_decision_schema() -> dict[str, Any]:
    return {
        "type": "OBJECT",
        "properties": {
            "slug": _string(),
            "decision": _string(
                enum=["direct", "host_managed", "excluded", "unsupported", "unclear"]
            ),
            "reason": _string(),
        },
        "required": ["slug", "decision", "reason"],
    }


def _requirements_schema() -> dict[str, Any]:
    return {
        "type": "OBJECT",
        "properties": {
            "schema_version": _string(enum=["1.0"]),
            "application_type": _string(nullable=True),
            "primary_function": _string(nullable=True),
            "target_users": _string_array(),
            "inputs": _string_array(),
            "outputs": _string_array(),
            "requires_ai": _boolean(),
            "requires_documents": _boolean(nullable=True),
            "document_formats": _string_array(),
            "requires_external_data": _boolean(nullable=True),
            "external_source_types": _string_array(),
            "requires_tools": _boolean(nullable=True),
            "requires_memory": _boolean(nullable=True),
            "memory_scope": _string(
                nullable=True,
                enum=["request", "session", "user", "organization"],
            ),
            "connection_ownership": _string(
                nullable=True,
                enum=["company", "end_user", "hybrid"],
            ),
            "integrations": {
                "type": "ARRAY",
                "items": _integration_requirement_schema(),
            },
            "integration_decisions": {
                "type": "ARRAY",
                "items": _integration_decision_schema(),
            },
            "requested_actions": _string_array(),
            "constraints": _string_array(),
            "data_sensitivity": _string(
                nullable=True,
                enum=["public", "internal", "confidential", "regulated"],
            ),
            "expected_scale": _string(
                nullable=True,
                enum=["prototype", "small", "medium", "large", "enterprise"],
            ),
            "assumptions": _string_array(),
            "confidence": _number(),
        },
        "required": [
            "schema_version",
            "application_type",
            "primary_function",
            "target_users",
            "inputs",
            "outputs",
            "requires_ai",
            "requires_documents",
            "document_formats",
            "requires_external_data",
            "external_source_types",
            "requires_tools",
            "requires_memory",
            "memory_scope",
            "connection_ownership",
            "integrations",
            "integration_decisions",
            "requested_actions",
            "constraints",
            "data_sensitivity",
            "expected_scale",
            "assumptions",
            "confidence",
        ],
    }


def onboarding_response_schema() -> dict[str, Any]:
    """Return the strict combined response schema for a model turn."""

    return {
        "type": "OBJECT",
        "properties": {
            "text": _string(),
            "proposed_intent": _string(
                enum=[
                    "set_use_case",
                    "set_use_case_and_mode",
                    "set_application_type",
                    "set_application_type_and_integrations",
                    "select_integrations",
                    "quick_bootstrap",
                    "clarify_requirements",
                    "requirements_ready",
                    "confirm_configuration",
                    "execute_provisioning",
                    "modify_settings",
                ]
            ),
            "proposed_data": {"type": "OBJECT"},
            "suggested_actions": _string_array(),
            "application_requirements": _requirements_schema(),
        },
        "required": [
            "text",
            "proposed_intent",
            "proposed_data",
            "suggested_actions",
            "application_requirements",
        ],
    }
