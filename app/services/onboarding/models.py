from __future__ import annotations

import inspect
import json
import logging
import re
from contextlib import nullcontext
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx
from pydantic import ValidationError

from app.schemas.onboarding_intelligence import ApplicationRequirements
from app.services.integrations.definitions import integration_registry
from app.services.onboarding.json_utils import parse_json_object
from app.services.onboarding.structured_schema import onboarding_response_schema
from app.services.onboarding.telemetry import current_trace, use_call

logger = logging.getLogger(__name__)


@dataclass
class OnboardingModelResponse:
    text: str
    proposed_intent: str | None = None
    proposed_data: dict[str, Any] = field(default_factory=dict)
    suggested_actions: list[str] = field(default_factory=list)
    # Production model responses may carry the typed requirements alongside
    # the conversational reply. This lets the normal path use one provider
    # request; the dedicated extractor remains a validated fallback when the
    # provider omits or corrupts this object.
    application_requirements: dict[str, Any] | None = None


class OnboardingModelProvider(Protocol):
    async def generate_step_response(
        self,
        user_message: str,
        current_state: str,
        current_config: dict[str, Any],
        history: list[dict[str, Any]],
    ) -> OnboardingModelResponse:
        ...


class FastOnboardingModelProvider:
    """Fast, deterministic, contextual conversational onboarding provider with structured interpretation."""

    _DISPLAY_NAMES: dict[str, str] = {
        "github": "GitHub",
        "slack": "Slack",
        "notion": "Notion",
        "postgres": "PostgreSQL",
        "mongodb": "MongoDB",
        "gmail": "Gmail",
        "s3": "Amazon S3",
        "redis": "Redis",
        "website": "Website Crawler",
        "mcp": "MCP Server",
        "document_storage": "Uploaded Documents",
        "google_drive": "Google Drive",
        "google_people": "Google People / Contacts",
        "google_sheets": "Google Sheets",
        "google_docs": "Google Docs",
        "google_chat": "Google Chat",
        "google_meet": "Google Meet",
        "google_forms": "Google Forms",
        "bigquery": "Google BigQuery",
        "google_cloud_storage": "Google Cloud Storage",
        "firestore": "Firestore",
        "google_analytics": "Google Analytics",
        "google_logging": "Google Cloud Logging",
        "google_monitoring": "Google Cloud Monitoring",
    }

    _USE_CASE_TITLES: dict[str, str] = {
        "autonomous_issue_triage_agent": "Autonomous Issue Triage Agent",
        "ai_customer_support": "AI Customer Support Agent",
        "developer_ai_assistant": "Developer AI Assistant",
        "architecture_analysis": "Architecture Analysis Runtime",
        "knowledge_search_rag": "Knowledge Search & RAG System",
        "autonomous_ai_agent": "Autonomous AI Agent",
        "saas_ai_copilot": "SaaS AI Copilot",
        "general_ai_application": "AI Application",
    }

    def _display_name(self, slug: str) -> str:
        return self._DISPLAY_NAMES.get(slug, slug.replace("_", " ").title())

    def _display_names_list(self, slugs: list[str]) -> str:
        names = [self._display_name(s) for s in slugs]
        if len(names) == 0:
            return ""
        if len(names) == 1:
            return names[0]
        if len(names) == 2:
            return f"{names[0]} and {names[1]}"
        return ", ".join(names[:-1]) + f", and {names[-1]}"

    def _use_case_title(self, slug: str) -> str:
        return self._USE_CASE_TITLES.get(slug, slug.replace("_", " ").title())

    def _context_aware_integration_question(self, use_case: str) -> tuple[str, list[str]]:
        if use_case == "architecture_analysis":
            return (
                "This runtime can receive a limited, sanitized context slice from your application "
                "without connecting directly to an external service. You can add approved integrations "
                "later if the workflow needs them.",
                ["Continue without integrations", "Add an integration later"],
            )
        if use_case == "autonomous_issue_triage_agent":
            return (
                "What data sources should your triage agent work with?\n\n"
                "It can pull issues and PRs from GitHub, post updates to Slack, "
                "reference internal docs, or query a database for context.",
                [
                    "GitHub issues and pull requests",
                    "GitHub, Slack, and internal docs",
                    "GitHub and PostgreSQL database",
                    "Help me choose",
                ],
            )
        if use_case == "ai_customer_support":
            return (
                "What should your support agent have access to?\n\n"
                "It can search uploaded documentation, query customer databases, "
                "or connect to Notion and Slack.",
                [
                    "Uploaded documentation and knowledge base",
                    "PostgreSQL customer data and Notion",
                    "Slack and uploaded support docs",
                    "Help me choose",
                ],
            )
        if use_case == "developer_ai_assistant":
            return (
                "What tools should your dev assistant connect to?\n\n"
                "It can browse repositories, search Slack channels, "
                "query databases, or reference internal docs.",
                [
                    "GitHub repos and Slack channels",
                    "GitHub, Notion wiki, and PostgreSQL",
                    "GitHub, Slack, and Notion",
                    "Help me choose",
                ],
            )
        if use_case == "knowledge_search_rag":
            return (
                "I understand this is a knowledge and operations assistant. "
                "Where should its knowledge come from, and should it use external sources when internal data is insufficient?\n\n"
                "You can index uploaded documents, Redis, PostgreSQL, Notion, GitHub, Slack, "
                "or crawled websites. External retrieval can be restricted to trusted domains and require citations.",
                [
                    "Internal sources only",
                    "Internal sources, then approved web search",
                    "Use trusted websites with citations",
                    "Help me choose",
                ],
            )
        return (
            "What data sources and tools should your runtime connect to?\n\n"
            "For example: GitHub for code, Slack for discussions, "
            "PostgreSQL for structured data, or uploaded documents for RAG.",
            [
                "GitHub and Slack",
                "PostgreSQL and uploaded documents",
                "Notion, GitHub, and Slack",
                "Help me choose",
            ],
        )

    async def generate_step_response(
        self,
        user_message: str,
        current_state: str,
        current_config: dict[str, Any],
        history: list[dict[str, Any]],
    ) -> OnboardingModelResponse:
        msg_lower = user_message.lower().strip()
        config = dict(current_config)

        # Check for direct confirmation
        if current_state in ("confirming_configuration", "configuring_runtime"):
            if any(k in msg_lower for k in ["confirm", "create", "yes", "looks good", "provision", "proceed", "ready"]):
                return OnboardingModelResponse(
                    text=(
                        "I’ll save this as a configuration draft. You can create a project "
                        "later to connect resources and provision the runtime."
                    ),
                    proposed_intent="execute_provisioning",
                    proposed_data={},
                    suggested_actions=["Create Project", "Review Configuration"],
                )

        # 1. State: onboarding_started
        if current_state == "onboarding_started":
            use_case = self._extract_use_case(msg_lower)
            detected_integrations = self._detect_integrations(msg_lower)
            has_user_connect = any(k in msg_lower for k in ["their own", "users connect", "user connect", "users' accounts", "byo", "mode b"])
            has_company_data = any(k in msg_lower for k in [
                "company data", "our company", "company's data", "internal data", "company-managed",
                "company managed", "mode a",
            ])
            uc_title = self._use_case_title(use_case)
            runtime_name = self._extract_runtime_name(msg_lower)
            name_hint = f" Runtime name: {runtime_name}." if runtime_name else ""

            if has_user_connect and not has_company_data:
                mode = "end_user_oauth"
            elif has_company_data and not has_user_connect:
                mode = "zyntry_managed"
            elif has_user_connect and has_company_data:
                mode = "hybrid"
            else:
                mode = None

            if mode:
                arch_desc = "let users connect their own accounts" if mode == "end_user_oauth" else "connect directly to your company data"
                integ_hint = f" with {self._display_names_list(detected_integrations)}" if detected_integrations else ""

                question, actions = self._context_aware_integration_question(use_case)
                return OnboardingModelResponse(
                    text=(
                        f"Configured {uc_title}{integ_hint} ({arch_desc}).{name_hint}\n\n"
                        f"{question}"
                    ),
                    proposed_intent="set_use_case_and_mode",
                    proposed_data={
                        "use_case": use_case,
                        "application_type": "customer_facing_ai_app" if mode == "end_user_oauth" else "internal_ai_agent",
                        "integration_mode": mode,
                        "integrations": detected_integrations,
                        "capabilities": {slug: self._default_capabilities(slug) for slug in detected_integrations},
                    },
                    suggested_actions=actions,
                )

            if detected_integrations:
                integ_text = self._display_names_list(detected_integrations)
                return OnboardingModelResponse(
                    text=(
                        f"Configured {uc_title} with {integ_text}.{name_hint}\n\n"
                        "Will this runtime connect to your company internal data, "
                        "or will end users connect their own external accounts?"
                    ),
                    proposed_intent="set_use_case",
                    proposed_data={
                        "use_case": use_case,
                        "integrations": detected_integrations,
                    },
                    suggested_actions=[
                        "Company data",
                        "End users connect accounts",
                        "Both",
                        "Not sure yet",
                    ],
                )
            else:
                if any(term in msg_lower for term in (
                    "no direct integration", "without integrations", "no integrations",
                    "do not configure", "don't configure", "do not use end-user oauth",
                )):
                    return OnboardingModelResponse(
                        text=(
                            f"Configured {uc_title} without direct integrations.{name_hint}\n\n"
                            "The runtime will receive the sanitized context supplied by your application. "
                            "You can add approved integrations later if needed."
                        ),
                        proposed_intent="set_use_case_and_mode",
                        proposed_data={
                            "use_case": use_case,
                            "application_type": "internal_ai_agent",
                            "integration_mode": "zyntry_managed",
                            "integrations": [],
                            "capabilities": {},
                        },
                        suggested_actions=["Continue without integrations", "Add an integration later"],
                    )
                return OnboardingModelResponse(
                    text=(
                        f"Configured {uc_title}.{name_hint}\n\n"
                        "Will this runtime connect to your company internal data, "
                        "or will end users connect their own external accounts?"
                    ),
                    proposed_intent="set_use_case",
                    proposed_data={
                        "use_case": use_case,
                        "integrations": [],
                    },
                    suggested_actions=[
                        "Company data",
                        "End users connect accounts",
                        "Both",
                        "Not sure yet",
                    ],
                )

        # 2. State: discovering_application_type
        if current_state in ("discovering_use_case", "discovering_application_type"):
            detected_integrations = self._detect_integrations(msg_lower)
            existing = list(config.get("integrations", []))
            for slug in existing:
                if slug not in detected_integrations:
                    detected_integrations.append(slug)

            use_case = config.get("use_case", "general_ai_application")

            if "not sure" in msg_lower or "unsure" in msg_lower or "default" in msg_lower or "skip" in msg_lower or "help" in msg_lower:
                mode = "zyntry_managed"
                app_type = "internal_ai_agent"
                desc = "Defaulting to company-managed connections. You can enable end-user OAuth anytime."
            elif "company" in msg_lower or "internal" in msg_lower or "our" in msg_lower or "mode a" in msg_lower:
                mode = "zyntry_managed"
                app_type = "internal_ai_agent"
                desc = "Runtime configured for company data and workspaces."
            elif "both" in msg_lower or "hybrid" in msg_lower:
                mode = "hybrid"
                app_type = "hybrid_ai_app"
                desc = "Runtime configured for hybrid mode (company data and user accounts)."
            elif any(k in msg_lower for k in ["user", "users", "their own", "byo", "mode b", "each"]):
                mode = "end_user_oauth"
                app_type = "customer_facing_ai_app"
                desc = "Runtime configured for end-user OAuth connections."
            else:
                mode = "zyntry_managed"
                app_type = "internal_ai_agent"
                desc = "Runtime configured for company-managed connections."

            if detected_integrations:
                caps = {slug: self._default_capabilities(slug) for slug in detected_integrations}
                integ_text = self._display_names_list(detected_integrations)

                cap_summary_parts = []
                for slug in detected_integrations:
                    defn = integration_registry.get(slug)
                    if defn:
                        read_caps = [c for c in defn.capabilities if not c.is_write]
                        if read_caps:
                            cap_summary_parts.append(f"{self._display_name(slug)} ({', '.join(c.name for c in read_caps[:2])})")
                        else:
                            cap_summary_parts.append(self._display_name(slug))

                cap_summary = ", ".join(cap_summary_parts) if cap_summary_parts else integ_text

                return OnboardingModelResponse(
                    text=(
                        f"{desc}\n\n"
                        f"Configured services: {cap_summary} with read access.\n\n"
                        "Choose your routing preference:\n"
                        "Low latency (fastest), balanced, or maximum quality."
                    ),
                    proposed_intent="set_application_type_and_integrations",
                    proposed_data={
                        "application_type": app_type,
                        "integration_mode": mode,
                        "integrations": detected_integrations,
                        "capabilities": caps,
                    },
                    suggested_actions=["Low latency", "Balanced", "Maximum quality"],
                )

            question, actions = self._context_aware_integration_question(use_case)
            return OnboardingModelResponse(
                text=(
                    f"{desc}\n\n"
                    f"{question}"
                ),
                proposed_intent="set_application_type",
                proposed_data={"application_type": app_type, "integration_mode": mode},
                suggested_actions=actions,
            )

        # 3. State: selecting_integrations
        if current_state in ("selecting_integrations", "selecting_capabilities"):
            detected_integrations = self._detect_integrations(msg_lower)
            existing = list(config.get("integrations", []))
            for slug in existing:
                if slug not in detected_integrations:
                    detected_integrations.append(slug)
            if not detected_integrations:
                detected_integrations = ["github", "slack"]

            caps = {}
            for slug in detected_integrations:
                defn = integration_registry.get(slug)
                if not defn:
                    continue
                available = [c.slug for c in defn.capabilities]
                selected = []
                if "search" in msg_lower:
                    selected.extend([c for c in available if "search" in c])
                if "file" in msg_lower or "read" in msg_lower:
                    selected.extend([c for c in available if "file" in c or "read" in c or "retrieval" in c])
                if "issue" in msg_lower or "triage" in msg_lower:
                    selected.extend([c for c in available if "issue" in c])
                if "pull" in msg_lower or "pr" in msg_lower:
                    selected.extend([c for c in available if "pull" in c or "pr" in c])
                if not selected:
                    selected = self._default_capabilities(slug)
                caps[slug] = list(dict.fromkeys(selected))

            integ_text = self._display_names_list(detected_integrations)
            return OnboardingModelResponse(
                text=(
                    f"Configured {integ_text} with standard capabilities.\n\n"
                    "Choose your routing preference:\n"
                    "Low latency, balanced, or maximum quality."
                ),
                proposed_intent="select_integrations",
                proposed_data={
                    "integrations": detected_integrations,
                    "capabilities": caps,
                },
                suggested_actions=["Low latency", "Balanced", "Maximum quality"],
            )

        # 4. State: configuring_runtime
        if current_state in ("configuring_runtime", "confirming_configuration"):
            strategy = self._extract_strategy(msg_lower)
            model, provider = self._strategy_to_model(strategy, msg_lower)
            env = self._extract_environment(msg_lower)

            preview_markdown = self._generate_preview_markdown(
                use_case=config.get("use_case", "ai_customer_support"),
                integration_mode=config.get("integration_mode", "end_user_oauth"),
                integrations=config.get("integrations", ["github", "slack"]),
                capabilities=config.get("capabilities", {}),
                routing_strategy=strategy,
                environment=env,
                runtime_name=config.get("runtime_name"),
            )

            return OnboardingModelResponse(
                text=preview_markdown,
                proposed_intent="confirm_configuration",
                proposed_data={
                    "model": model,
                    "provider": provider,
                    "routing_strategy": strategy,
                    "environment": env,
                },
                suggested_actions=["Confirm & Create Runtime", "Change settings"],
            )

        return OnboardingModelResponse(
            text="Updated your runtime configuration.",
            proposed_intent="general_update",
            proposed_data={},
            suggested_actions=["Confirm & Create Runtime", "Continue"],
        )

    def _extract_use_case(self, msg: str) -> str:
        cleaned = re.sub(r"example integration stack:?.*", "", msg, flags=re.IGNORECASE)
        cleaned = re.sub(r"example integrations:?.*", "", cleaned, flags=re.IGNORECASE).strip()

        # Prefer an explicit application description over incidental words in
        # a long capability list (for example, GitHub issues in a knowledge
        # assistant description should not turn it into an issue-triage app).
        if any(term in cleaned for term in (
            "architecture investigation", "architecture analysis", "software architecture",
            "call graph", "dependency graph", "data-flow analysis", "engineering graph",
        )):
            return "architecture_analysis"
        if any(term in cleaned for term in ("operations and knowledge", "knowledge assistant", "ai operations")):
            return "knowledge_search_rag"
        if "triage" in cleaned or "engineer" in cleaned or "issue" in cleaned:
            return "autonomous_issue_triage_agent"
        if "support" in cleaned or "customer" in cleaned:
            return "ai_customer_support"
        if "code" in cleaned or "developer" in cleaned:
            return "developer_ai_assistant"
        if "rag" in cleaned or "knowledge" in cleaned or "search" in cleaned:
            return "knowledge_search_rag"
        if "agent" in cleaned:
            return "autonomous_ai_agent"
        if "saas" in cleaned:
            return "saas_ai_copilot"
        return "general_ai_application"

    def _detect_integrations(self, msg: str) -> list[str]:
        msg = msg.lower()
        if any(term in msg for term in (
            "no direct integration", "without integrations", "no integrations",
            "do not configure", "don't configure", "do not use end-user oauth",
        )):
            return []
        found: list[str] = []
        slugs = integration_registry.list_slugs()
        for slug in slugs:
            if slug in msg or slug.replace("_", " ") in msg:
                found.append(slug)
        if "git" in msg or "repo" in msg:
            if "github" not in found:
                found.append("github")
        if "slack" in msg or "channel" in msg:
            if "slack" not in found:
                found.append("slack")
        if "notion" in msg or "wiki" in msg:
            if "notion" not in found:
                found.append("notion")
        if "postgres" in msg or "sql" in msg or "database" in msg:
            if "postgresql" not in found and "postgres" not in found:
                found.append("postgresql")
        if "mongo" in msg:
            if "mongodb" not in found:
                found.append("mongodb")
        if "gmail" in msg or "mail" in msg:
            if "gmail" not in found:
                found.append("gmail")
        google_aliases = {
            "sheets": "google_sheets",
            "spreadsheets": "google_sheets",
            "google sheet": "google_sheets",
            "google docs": "google_docs",
            "google document": "google_docs",
            "google chat": "google_chat",
            "google meet": "google_meet",
            "google forms": "google_forms",
            "big query": "bigquery",
            "bigquery": "bigquery",
            "cloud storage": "google_cloud_storage",
            "gcs": "google_cloud_storage",
            "firestore": "firestore",
            "firebase": "firestore",
            "analytics": "google_analytics",
            "cloud logging": "google_logging",
            "cloud monitoring": "google_monitoring",
        }
        for phrase, slug in google_aliases.items():
            if phrase in msg and slug not in found:
                found.append(slug)
        if any(k in msg for k in ["document", "documentation", "upload", "docs", "pdf", "rag"]):
            if "document_storage" not in found:
                found.append("document_storage")
        # Keep the catalog's canonical slug and remove case/alias duplicates.
        normalized: list[str] = []
        seen: set[str] = set()
        for slug in found:
            definition = integration_registry.get(slug)
            canonical = definition.slug if definition else slug
            if canonical not in seen:
                seen.add(canonical)
                normalized.append(canonical)
        return normalized

    @staticmethod
    def _extract_runtime_name(msg: str) -> str | None:
        """Extract an explicit runtime name from natural-language onboarding.

        Onboarding messages commonly start with phrases such as
        ``Create a runtime named LearnFlow Assistant`` or ``Name the runtime:
        Atlas``.  The old extractor only understood the latter form, so the
        former silently fell back to a use-case-derived name (for example,
        ``Ai Customer Support Runtime``).  Keep this deliberately narrow: we
        only capture text immediately following an explicit naming phrase and
        stop at a sentence/newline boundary so the rest of a long requirements
        prompt is never treated as part of the name.
        """
        if not isinstance(msg, str) or not msg.strip():
            return None

        naming_patterns = (
            # ``Create/build/provision a runtime named/called Foo``
            r"(?:create|build|provision|configure)\s+(?:an?\s+)?runtime\s+(?:named|called|with\s+name)\s*[:\-]?\s*",
            # ``Name the runtime Foo`` / ``Runtime name: Foo``
            r"(?:name\s+(?:the\s+)?runtime|runtime\s+(?:named|name))\s*[:\-]?\s*",
            # ``Call the runtime Foo`` / ``Call it Foo``
            r"call\s+(?:(?:the\s+)?runtime|it)\s*[:\-]?\s*",
        )

        for prefix in naming_patterns:
            match = re.search(
                prefix + r"[`\"']?([^`\"'\n.!?;]+)",
                msg,
                flags=re.IGNORECASE,
            )
            if not match:
                continue
            name = re.sub(r"\s+", " ", match.group(1)).strip(" ,:;.!?")
            if name:
                return name[:255]

        return None

    def _default_capabilities(self, slug: str) -> list[str]:
        defn = integration_registry.get(slug)
        if defn:
            return [c.slug for c in defn.capabilities if not c.is_write]
        return []

    def _extract_strategy(self, msg: str) -> str:
        if "fast" in msg or "speed" in msg or "latency" in msg or "low" in msg:
            return "latency_optimized"
        if "intel" in msg or "max" in msg or "best" in msg or "quality" in msg or "high" in msg:
            return "quality_optimized"
        return "balanced"

    def _strategy_to_model(self, strategy: str, msg: str) -> tuple[str, str]:
        if "claude" in msg or "sonnet" in msg:
            return "claude-3-5-sonnet-20241022", "anthropic"
        if "deepseek" in msg:
            return "deepseek-chat", "deepseek"
        if strategy == "latency_optimized":
            return "gpt-4o-mini", "openai"
        if strategy == "quality_optimized":
            return "gpt-4o", "openai"
        return "gpt-4o", "openai"

    def _extract_environment(self, msg: str) -> str:
        if "prod" in msg:
            return "production"
        if "stag" in msg:
            return "staging"
        return "development"

    def _generate_preview_markdown(
        self,
        use_case: str,
        integration_mode: str,
        integrations: list[str],
        capabilities: dict[str, list[str]],
        routing_strategy: str,
        environment: str,
        runtime_name: str | None = None,
    ) -> str:
        uc_title = runtime_name or self._use_case_title(use_case)
        display_name = uc_title if runtime_name else f"{uc_title} Runtime"
        strategy_labels = {
            "latency_optimized": "Low latency",
            "quality_optimized": "Maximum quality",
            "balanced": "Balanced",
        }
        strategy_label = strategy_labels.get(routing_strategy, routing_strategy.replace("_", " ").capitalize())

        arch_labels = {
            "end_user_oauth": "End-user OAuth (each user connects their own accounts)",
            "zyntry_managed": "Company-managed data and credentials",
            "hybrid": "Hybrid (company data and end-user accounts)",
        }
        arch_label = arch_labels.get(integration_mode, integration_mode.replace("_", " ").capitalize())

        integ_sections = []
        for slug in integrations:
            display = self._display_name(slug)
            caps = capabilities.get(slug, self._default_capabilities(slug))
            if caps:
                defn = integration_registry.get(slug)
                if defn:
                    cap_map = {c.slug: c.name for c in defn.capabilities}
                    cap_names = [cap_map.get(c, c.replace("_", " ").capitalize()) for c in caps]
                else:
                    cap_names = [c.replace("_", " ").capitalize() for c in caps]
                integ_sections.append(f"• {display}: {', '.join(cap_names)}")
            else:
                integ_sections.append(f"• {display}: Standard read access")

        integ_block = "\n".join(integ_sections) if integ_sections else "• None configured"

        return (
            "Runtime Summary\n\n"
            f"• Name: {display_name}\n"
            f"• Mode: {arch_label}\n"
            f"• Routing: {strategy_label}\n"
            f"• Environment: {environment.capitalize()}\n\n"
            f"Connected Services:\n{integ_block}\n\n"
            "Configuration draft ready. Create a project later to connect resources and provision the runtime."
        )


class ConfiguredOnboardingModelProvider:
    """Model-first conversational provider for free-form runtime creation.

    The model interprets the conversation and proposes a typed onboarding
    action. The engine still validates that action against the integration
    registry and the user's permissions before changing state. Provider
    selection is routed across configured model providers; the fast provider
    is retained only as an explicitly enabled development fallback.
    """

    _ALLOWED_INTENTS = {
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
    }

    def __init__(self, fallback: FastOnboardingModelProvider | None = None) -> None:
        self.fallback = fallback or FastOnboardingModelProvider()

    @staticmethod
    def _provider() -> tuple[Any | None, str]:
        """Build the provider router lazily to avoid import cycles."""
        from app.services.onboarding.provider_router import build_onboarding_provider

        return build_onboarding_provider()

    @staticmethod
    def _capability_manifest() -> list[dict[str, Any]]:
        manifest: list[dict[str, Any]] = []
        for slug in integration_registry.list_slugs():
            definition = integration_registry.get(slug)
            if not definition:
                continue
            manifest.append(
                {
                    "slug": definition.slug,
                    "name": definition.name,
                    "status": definition.status,
                    "enabled": definition.enabled,
                    "connection_modes": sorted(definition.supported_connection_modes),
                    "capabilities": [
                        {"slug": capability.slug, "write": bool(capability.is_write)}
                        for capability in definition.capabilities
                    ],
                }
            )
        return manifest

    @staticmethod
    def _safe_config(config: dict[str, Any]) -> dict[str, Any]:
        safe: dict[str, Any] = {}
        for key, value in config.items():
            lowered = key.lower()
            if any(secret in lowered for secret in ("password", "secret", "token", "api_key", "credential")):
                continue
            safe[key] = value
        return safe

    @staticmethod
    def _provider_metadata(provider: Any) -> dict[str, Any]:
        """Return bounded provider diagnostics without prompt or secret data."""

        metadata: dict[str, Any] = {
            "finish_reason": getattr(provider, "last_finish_reason", None) or "unknown",
            "response_schema_applied": bool(
                getattr(provider, "last_response_schema_applied", False)
            ),
            "schema_has_refs": bool(getattr(provider, "last_schema_has_refs", False)),
        }
        error_metadata = getattr(provider, "last_error_metadata", {})
        if isinstance(error_metadata, dict):
            for key in ("type", "code", "param"):
                value = error_metadata.get(key)
                if isinstance(value, str) and value:
                    metadata[f"provider_error_{key}"] = value[:120]
        return metadata

    @staticmethod
    def _response_failure_stage(error: BaseException) -> str:
        message = str(error).lower()
        if "json" in message or "object" in message:
            return "json_parse"
        if "application_requirements" in message or "unsupported intent" in message:
            return "schema_validation"
        return "response_validation"

    @staticmethod
    def _parse_response(content: str) -> OnboardingModelResponse:
        try:
            value = parse_json_object(content)
        except ValueError as exc:
            # Keep the provider-facing error stable while allowing the shared
            # parser to repair safe syntax errors before validation.
            raise ValueError(str(exc).replace("Model response", "Onboarding model response")) from exc
        intent = value.get("proposed_intent")
        if not isinstance(intent, str):
            intent = "clarify_requirements"
        intent = intent.strip().lower()
        intent_aliases = {
            "clarify": "clarify_requirements",
            "clarification": "clarify_requirements",
            "ask_question": "clarify_requirements",
            "ask_clarifying_question": "clarify_requirements",
            "collect_requirements": "clarify_requirements",
            "ready": "requirements_ready",
            "complete": "execute_provisioning",
        }
        intent = intent_aliases.get(intent, intent)
        # JSON mode is intentionally less strict than native structured
        # output. If a provider omits or renames the intent, keep the turn
        # read-only and let the backend clarification logic decide the next
        # question rather than rejecting the entire onboarding request.
        if intent not in ConfiguredOnboardingModelProvider._ALLOWED_INTENTS:
            intent = "clarify_requirements"
        text = value.get("text")
        if not isinstance(text, str) or not text.strip():
            text = "I’ve captured the information so far. I need one more detail to continue."
        proposed_data = value.get("proposed_data", {})
        if not isinstance(proposed_data, dict):
            proposed_data = {}
        suggested_actions = value.get("suggested_actions", [])
        if not isinstance(suggested_actions, list):
            suggested_actions = []
        embedded_requirements = value.get("application_requirements")
        if embedded_requirements is None and isinstance(proposed_data, dict):
            embedded_requirements = proposed_data.get("application_requirements")
        # JSON mode guarantees valid JSON, but it does not enforce the nested
        # onboarding contract. Older/provider-compatible models may omit the
        # object on an early conversational turn. Treat that as an empty,
        # incomplete requirements snapshot so the backend can ask the next
        # clarification question instead of failing the whole turn.
        if embedded_requirements is None:
            embedded_requirements = {}
        if not isinstance(embedded_requirements, dict):
            raise ValueError("Onboarding model application_requirements must be an object")
        try:
            # Validate the combined response before it reaches the engine. A
            # malformed requirements object gets one bounded repair attempt;
            # it no longer triggers a second full extraction request.
            from app.services.onboarding.intelligence import ModelBackedRequirementsExtractor

            normalized_requirements = ModelBackedRequirementsExtractor._prepare_model_payload(
                embedded_requirements
            )
            validated_requirements = ApplicationRequirements.model_validate(normalized_requirements)
            normalized_requirements = validated_requirements.model_dump(mode="json")
        except ValidationError as exc:
            raise ValueError("Onboarding model application_requirements is invalid") from exc
        suggested_actions = [item for item in suggested_actions if isinstance(item, str)]

        # The model may return a display object instead of a slug despite the
        # prompt. Normalize it here and discard unknown connectors before the
        # engine applies any state transition. This prevents a model response
        # from bypassing the configured capability registry.
        normalized_data = dict(proposed_data)
        raw_integrations = normalized_data.get("integrations")
        if isinstance(raw_integrations, list):
            integrations: list[str] = []
            unsupported: list[str] = []
            coming_soon: list[str] = []
            for item in raw_integrations:
                slug = item.get("slug") if isinstance(item, dict) else item
                if not isinstance(slug, str):
                    continue
                requested_slug = slug.strip().lower()
                definition = integration_registry.get(requested_slug)
                if (
                    definition
                    and definition.enabled
                    and definition.status not in {"disabled", "deprecated", "coming_soon"}
                    and definition.slug not in integrations
                ):
                    integrations.append(definition.slug)
                elif definition and (
                    not definition.enabled
                    or definition.status in {"disabled", "deprecated", "coming_soon"}
                ):
                    if definition.name not in coming_soon:
                        coming_soon.append(definition.name)
                elif requested_slug not in unsupported:
                    unsupported.append(slug.strip())
            normalized_data["integrations"] = integrations
            if unsupported:
                normalized_data["unsupported_integrations"] = unsupported
            if coming_soon:
                normalized_data["coming_soon_integrations"] = coming_soon

        return OnboardingModelResponse(
            text=text.strip(),
            proposed_intent=intent,
            proposed_data=normalized_data,
            suggested_actions=[item.strip() for item in suggested_actions if item.strip()][:8],
            application_requirements=normalized_requirements,
        )

    @staticmethod
    async def _generate_structured(
        provider: Any,
        *,
        messages: list[dict[str, str]],
        model: str,
        max_tokens: int,
        temperature: float,
    ) -> tuple[str, int]:
        """Generate one onboarding response with native schema constraints.

        Routed Gemini providers accept ``response_schema`` and forward it to
        ``responseSchema``. Test doubles and other provider adapters may not
        expose that keyword, so they retain the JSON-prompt compatibility
        path without affecting the production Gemini path.
        """

        generate = provider.generate
        parameters = inspect.signature(generate).parameters
        supports_schema = "response_schema" in parameters or any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        )
        kwargs: dict[str, Any] = {
            "messages": messages,
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if supports_schema:
            kwargs["response_schema"] = onboarding_response_schema()
        return await generate(**kwargs)

    async def generate_step_response(
        self,
        user_message: str,
        current_state: str,
        current_config: dict[str, Any],
        history: list[dict[str, Any]],
    ) -> OnboardingModelResponse:
        from app.core.config import settings

        provider, model = self._provider()
        if provider is None:
            if bool(getattr(settings, "ONBOARDING_ALLOW_FALLBACK", False)):
                response = await self.fallback.generate_step_response(
                    user_message, current_state, current_config, history
                )
                trace = current_trace()
                if trace:
                    fallback_call_id = trace.start_call(
                        operation="conversation_response",
                        model=model,
                        messages=[],
                    )
                    trace.finish_call(
                        fallback_call_id,
                        status="fallback",
                        provider="local",
                        model="rule_based",
                        output_text=response.text,
                        fallback_used=True,
                    )
                return response
            from app.services.onboarding.intelligence import OnboardingModelUnavailableError

            trace = current_trace()
            if trace:
                unavailable_call_id = trace.start_call(operation="conversation_response", model=model, messages=[])
                trace.finish_call(
                    unavailable_call_id,
                    status="failed",
                    provider="unconfigured",
                    model=model,
                    error=RuntimeError("onboarding provider is not configured"),
                )
            raise OnboardingModelUnavailableError(
                "The configured onboarding model is unavailable."
            )

        system = """You are Zyntry's conversational runtime architect.
Interpret the user's natural-language description of any AI application and
propose the next onboarding action. Do not restrict the user to predefined
use-case templates. Use the capability manifest as the source of truth for
supported integrations and capabilities; never invent a connector or claim a
capability that is not listed. Do not select integrations marked disabled,
deprecated, or coming_soon.

Return exactly one JSON object with these keys:
text (a concise natural-language reply), proposed_intent (one of the allowed
intents), proposed_data (safe configuration changes), suggested_actions
(zero to eight short choices), and application_requirements. The
application_requirements object must match schema version 1.0 and must reflect
the entire conversation. Include these fields in that object: application_type,
primary_function, target_users, inputs, outputs, requires_documents,
document_formats, requires_external_data, external_source_types,
requires_tools, requires_memory, memory_scope, connection_ownership,
integrations, integration_decisions, requested_actions, constraints,
data_sensitivity, expected_scale, confidence, and assumptions. Use null or an
empty array when a value is not known yet. Never include credentials, secrets, private
data, hidden reasoning, or markdown outside the JSON object.

If the user requests a connector that is not in the manifest, put its name in
proposed_data.unsupported_integrations. If it is marked coming_soon or
disabled, put its name in proposed_data.coming_soon_integrations. Do not put
either kind in proposed_data.integrations; explain that it was left out and
ask whether the user wants to continue with available sources.

Ask a focused clarification question when the requirements extractor has not
captured enough information. Never execute provisioning or a write action
unless the user has explicitly confirmed it. Do not use a generic "Does this
sound right?" confirmation when a specific requirement is still missing.
For company data versus
end-user OAuth, preserve the ownership stated by the user. Runtime creation
stores a draft; project attachment and connector authorization happen later.
"""
        payload = {
            "current_state": current_state,
            "current_config": self._safe_config(current_config),
            "recent_conversation": history[-max(1, int(getattr(settings, "ONBOARDING_HISTORY_TURNS", 6))):],
            "latest_message": user_message,
            "capability_manifest": self._capability_manifest(),
            "allowed_intents": sorted(self._ALLOWED_INTENTS),
        }
        trace = current_trace()
        call_id = trace.start_call(
            operation="conversation_response",
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(payload, default=str)},
            ],
        ) if trace else None
        content = ""
        try:
            with use_call(call_id) if call_id else nullcontext():
                model_messages = [
                    {"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(payload, default=str)},
                ]
                # The routed production provider forwards this schema to
                # Gemini's native constrained-decoding API. Test doubles and
                # non-Gemini providers continue through the compatibility path.
                content, usage = await self._generate_structured(
                    provider,
                    messages=model_messages,
                    model=model,
                    max_tokens=int(getattr(settings, "ONBOARDING_MAX_OUTPUT_TOKENS", 2048)),
                    temperature=0.25,
                )
            response = self._parse_response(content)
            if trace and call_id:
                attempts = len(getattr(provider, "last_attempts", []) or []) or 1
                trace.finish_call(
                    call_id,
                    status="completed",
                    provider=getattr(provider, "last_provider", None),
                    model=getattr(provider, "last_model", None) or model,
                    usage=usage,
                    output_text=content,
                    attempts=attempts,
                    fallback_used=False,
                    http_status=getattr(provider, "last_status_code", None),
                    metadata=self._provider_metadata(provider),
                )
            return response
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "Onboarding conversational provider returned HTTP %s",
                exc.response.status_code,
            )
            from app.services.onboarding.intelligence import (
                OnboardingModelRateLimitedError,
                OnboardingModelUnavailableError,
            )

            if bool(getattr(settings, "ONBOARDING_ALLOW_FALLBACK", False)):
                if trace and call_id:
                    trace.finish_call(
                        call_id,
                        status="fallback",
                        provider=getattr(provider, "last_provider", None),
                        model=getattr(provider, "last_model", None) or model,
                        error=exc,
                        attempts=len(getattr(provider, "last_attempts", []) or []) or 1,
                        fallback_used=True,
                        metadata=self._provider_metadata(provider),
                    )
                return await self.fallback.generate_step_response(
                    user_message, current_state, current_config, history
                )
            if exc.response.status_code == 429:
                if trace and call_id:
                    trace.finish_call(
                        call_id,
                        status="failed",
                        provider=getattr(provider, "last_provider", None),
                        model=getattr(provider, "last_model", None) or model,
                        error=exc,
                        attempts=len(getattr(provider, "last_attempts", []) or []) or 1,
                        http_status=exc.response.status_code,
                        metadata=self._provider_metadata(provider),
                    )
                raise OnboardingModelRateLimitedError(
                    "The configured onboarding provider is rate limited."
                ) from exc
            if trace and call_id:
                trace.finish_call(
                    call_id,
                    status="failed",
                    provider=getattr(provider, "last_provider", None),
                    model=getattr(provider, "last_model", None) or model,
                    error=exc,
                    attempts=len(getattr(provider, "last_attempts", []) or []) or 1,
                    http_status=exc.response.status_code,
                    metadata=self._provider_metadata(provider),
                )
            raise OnboardingModelUnavailableError(
                "The configured onboarding provider rejected the request."
            ) from exc
        except httpx.RequestError as exc:
            logger.warning(
                "Onboarding conversational provider request failed: %s",
                type(exc).__name__,
            )
            from app.services.onboarding.intelligence import OnboardingModelUnavailableError

            if bool(getattr(settings, "ONBOARDING_ALLOW_FALLBACK", False)):
                if trace and call_id:
                    trace.finish_call(call_id, status="fallback", error=exc, attempts=len(getattr(provider, "last_attempts", []) or []) or 1, fallback_used=True, metadata=self._provider_metadata(provider))
                return await self.fallback.generate_step_response(
                    user_message, current_state, current_config, history
                )
            if trace and call_id:
                trace.finish_call(call_id, status="failed", error=exc, attempts=len(getattr(provider, "last_attempts", []) or []) or 1, metadata=self._provider_metadata(provider))
            raise OnboardingModelUnavailableError(
                "The configured onboarding provider could not be reached."
            ) from exc
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            # A schema-constrained provider should almost never reach this
            # branch. Keep exactly one repair request for older models or
            # providers that ignore responseSchema; never chain repairs.
            if trace and call_id:
                trace.finish_call(
                    call_id,
                    status="failed",
                    provider=getattr(provider, "last_provider", None),
                    model=getattr(provider, "last_model", None) or model,
                    error=exc,
                    attempts=len(getattr(provider, "last_attempts", []) or []) or 1,
                    http_status=getattr(provider, "last_status_code", None),
                    metadata={
                        **self._provider_metadata(provider),
                        "response_failure_stage": self._response_failure_stage(exc),
                    },
                )
            repair_id = trace.start_call(
                operation="conversation_repair",
                model=model,
                messages=[],
            ) if trace else None
            repair_messages = [
                {
                    "role": "system",
                    "content": (
                        system
                        + "\nThe previous response failed validation. Return one valid JSON object "
                        "matching the supplied response schema. Do not add markdown or commentary."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "malformed_response": content,
                            "latest_message": user_message,
                            "current_state": current_state,
                            "current_config": self._safe_config(current_config),
                        },
                        default=str,
                    ),
                },
            ]
            try:
                with use_call(repair_id) if repair_id else nullcontext():
                    repaired_content, repaired_usage = await self._generate_structured(
                        provider,
                        messages=repair_messages,
                        model=model,
                        max_tokens=int(getattr(settings, "ONBOARDING_MAX_OUTPUT_TOKENS", 2048)),
                        temperature=0.1,
                    )
                repaired_response = self._parse_response(repaired_content)
                if trace and repair_id:
                    trace.finish_call(
                        repair_id,
                        status="repaired",
                        provider=getattr(provider, "last_provider", None),
                        model=getattr(provider, "last_model", None) or model,
                        usage=repaired_usage,
                        output_text=repaired_content,
                        attempts=len(getattr(provider, "last_attempts", []) or []) or 1,
                        http_status=getattr(provider, "last_status_code", None),
                        metadata=self._provider_metadata(provider),
                    )
                return repaired_response
            except httpx.HTTPStatusError as repair_exc:
                if trace and repair_id:
                    trace.finish_call(
                        repair_id,
                        status="failed",
                        provider=getattr(provider, "last_provider", None),
                        model=getattr(provider, "last_model", None) or model,
                        error=repair_exc,
                        http_status=repair_exc.response.status_code,
                        metadata=self._provider_metadata(provider),
                    )
                from app.services.onboarding.intelligence import (
                    OnboardingModelRateLimitedError,
                    OnboardingModelUnavailableError,
                )

                if repair_exc.response.status_code == 429:
                    raise OnboardingModelRateLimitedError(
                        "The configured onboarding provider is rate limited."
                    ) from repair_exc
                raise OnboardingModelUnavailableError(
                    "The configured onboarding provider rejected the repair request."
                ) from repair_exc
            except httpx.RequestError as repair_exc:
                if trace and repair_id:
                    trace.finish_call(
                        repair_id,
                        status="failed",
                        provider=getattr(provider, "last_provider", None),
                        model=getattr(provider, "last_model", None) or model,
                        error=repair_exc,
                        metadata=self._provider_metadata(provider),
                    )
                from app.services.onboarding.intelligence import OnboardingModelUnavailableError

                raise OnboardingModelUnavailableError(
                    "The configured onboarding provider could not be reached."
                ) from repair_exc
            except Exception as repair_exc:
                logger.warning(
                    "Onboarding conversational response repair failed type=%s provider=%s model=%s status=%s",
                    type(repair_exc).__name__,
                    getattr(provider, "last_provider", None) or "unknown",
                    getattr(provider, "last_model", None) or model,
                    getattr(provider, "last_status_code", None) or "unknown",
                )
                if trace and repair_id:
                    trace.finish_call(
                        repair_id,
                        status="failed",
                        provider=getattr(provider, "last_provider", None),
                        model=getattr(provider, "last_model", None) or model,
                        error=repair_exc,
                        http_status=getattr(provider, "last_status_code", None),
                        metadata={
                            **self._provider_metadata(provider),
                            "response_failure_stage": self._response_failure_stage(repair_exc),
                        },
                    )
                from app.services.onboarding.intelligence import OnboardingModelResponseError

                raise OnboardingModelResponseError(
                    "The onboarding model returned an invalid response."
                ) from repair_exc
        except Exception as exc:
            logger.exception("Onboarding conversational model failed")
            from app.services.onboarding.intelligence import OnboardingModelResponseError

            if bool(getattr(settings, "ONBOARDING_ALLOW_FALLBACK", False)):
                if trace and call_id:
                    trace.finish_call(call_id, status="fallback", error=exc, attempts=len(getattr(provider, "last_attempts", []) or []) or 1, fallback_used=True, metadata=self._provider_metadata(provider))
                return await self.fallback.generate_step_response(
                    user_message, current_state, current_config, history
                )
            if trace and call_id:
                trace.finish_call(call_id, status="failed", error=exc, attempts=len(getattr(provider, "last_attempts", []) or []) or 1, metadata=self._provider_metadata(provider))
            raise OnboardingModelResponseError(
                "The onboarding model returned an invalid response."
            ) from exc

    def _extract_runtime_name(self, message: str) -> str | None:
        """Keep the engine's name extraction compatible with the fallback."""
        return self.fallback._extract_runtime_name(message)


default_onboarding_model_provider = ConfiguredOnboardingModelProvider()


