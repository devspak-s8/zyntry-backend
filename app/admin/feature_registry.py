from __future__ import annotations

from dataclasses import dataclass

from app.admin.constants import FeatureFlagType, FeatureScope


@dataclass(frozen=True, slots=True)
class SystemFeatureDefinition:
    key: str
    name: str
    description: str
    scope: FeatureScope
    flag_type: FeatureFlagType
    enabled: bool
    default_value: bool
    rollout_percentage: int


def _stable(
    key: str,
    name: str,
    description: str,
    scope: FeatureScope,
) -> SystemFeatureDefinition:
    return SystemFeatureDefinition(
        key=key,
        name=name,
        description=description,
        scope=scope,
        flag_type=FeatureFlagType.TOGGLE,
        enabled=True,
        default_value=True,
        rollout_percentage=100,
    )


def _beta(
    key: str,
    name: str,
    description: str,
    scope: FeatureScope,
) -> SystemFeatureDefinition:
    return SystemFeatureDefinition(
        key=key,
        name=name,
        description=description,
        scope=scope,
        flag_type=FeatureFlagType.PERCENTAGE,
        enabled=True,
        default_value=False,
        rollout_percentage=0,
    )


SYSTEM_FEATURES: tuple[SystemFeatureDefinition, ...] = (
    _stable(
        "dashboard",
        "Dashboard",
        "Dashboard overview and setup experience.",
        FeatureScope.EXPERIMENTAL,
    ),
    _stable(
        "knowledge_bases",
        "Knowledge bases",
        "Knowledge bases and document management.",
        FeatureScope.KNOWLEDGE,
    ),
    _beta(
        "knowledge_sources",
        "Knowledge sources",
        "External knowledge source connections and synchronization.",
        FeatureScope.KNOWLEDGE,
    ),
    _beta(
        "provider_connections",
        "Provider connections",
        "External AI provider connection management.",
        FeatureScope.PROVIDER,
    ),
    _beta(
        "tools_connectors",
        "Tools and connectors",
        "Connected tools, credentials, and OAuth integrations.",
        FeatureScope.TOOL,
    ),
    _stable(
        "ai_models", "AI models", "AI model catalogue and configuration.", FeatureScope.PROVIDER
    ),
    _beta(
        "model_routing",
        "Model routing",
        "Model recommendations and routing strategies.",
        FeatureScope.ROUTING,
    ),
    _stable(
        "runtime_management",
        "Runtime management",
        "Runtime creation, building, and configuration.",
        FeatureScope.RUNTIME,
    ),
    _stable(
        "runtime_console",
        "Runtime Console",
        "Runtime chat, invocation, telemetry, and SDK access.",
        FeatureScope.RUNTIME,
    ),
    _beta(
        "runtime_assistant_beta",
        "Runtime Assistant beta",
        "Runtime diagnostics and optimization assistant.",
        FeatureScope.RUNTIME,
    ),
    _stable(
        "deployments",
        "Deployments",
        "Deployment details and integration snippets.",
        FeatureScope.RUNTIME,
    ),
    _stable(
        "api_keys",
        "API keys",
        "API key creation, scopes, rotation, and revocation.",
        FeatureScope.RUNTIME,
    ),
    _stable(
        "analytics",
        "Analytics",
        "Usage analytics, summaries, and reporting.",
        FeatureScope.EXPERIMENTAL,
    ),
    _beta(
        "observability",
        "Observability",
        "Request logs, events, telemetry, and diagnostics.",
        FeatureScope.EXPERIMENTAL,
    ),
    _stable(
        "billing",
        "Billing",
        "Wallets, transactions, usage, budgets, and pricing.",
        FeatureScope.BILLING,
    ),
    _stable(
        "credit_purchases",
        "Credit purchases",
        "Credit checkout and purchase flow.",
        FeatureScope.BILLING,
    ),
    _beta("actions", "Actions", "Connected action execution and confirmation.", FeatureScope.TOOL),
    _beta(
        "workflows",
        "Workflows",
        "Workflow design, validation, and execution.",
        FeatureScope.EXPERIMENTAL,
    ),
    _beta(
        "webhooks",
        "Webhooks",
        "Outgoing webhook management and delivery replay.",
        FeatureScope.EXPERIMENTAL,
    ),
    _stable(
        "developer_settings",
        "Developer settings",
        "Developer account and application settings.",
        FeatureScope.EXPERIMENTAL,
    ),
)

SYSTEM_FEATURES_BY_KEY: dict[str, SystemFeatureDefinition] = {
    feature.key: feature for feature in SYSTEM_FEATURES
}
STABLE_FEATURE_KEYS: frozenset[str] = frozenset(
    feature.key for feature in SYSTEM_FEATURES if feature.default_value
)
BETA_FEATURE_KEYS: frozenset[str] = frozenset(
    feature.key for feature in SYSTEM_FEATURES if not feature.default_value
)
