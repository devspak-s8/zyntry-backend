from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.services.integrations.definitions import integration_registry

logger = logging.getLogger(__name__)


@dataclass
class OnboardingModelResponse:
    text: str
    proposed_intent: str | None = None
    proposed_data: dict[str, Any] = field(default_factory=dict)
    suggested_actions: list[str] = field(default_factory=list)


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
            has_company_data = any(k in msg_lower for k in ["company data", "our company", "company's data", "internal data", "mode a"])
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
        match = re.search(
            r"(?:name the runtime|runtime name|call (?:the )?runtime)\s*[:\-]?\s*[`\"']?([^`\"'\.\n]+)",
            msg,
            flags=re.IGNORECASE,
        )
        if not match:
            return None
        name = re.sub(r"\s+", " ", match.group(1)).strip(" ,:;")
        return name[:255] if name else None

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
            f"• Name: {uc_title} Runtime\n"
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
    registry and the user's permissions before changing state. The fast
    provider is retained only as an availability fallback when no provider
    credential is configured or a model response cannot be validated.
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
        """Build the configured provider lazily to avoid import cycles."""
        from app.core.config import settings
        from app.services.rag import AnthropicLLMProvider, OpenAILLMProvider

        preferred = getattr(settings, "ONBOARDING_PROVIDER", "google").lower()
        model = getattr(settings, "ONBOARDING_MODEL", "gemini-2.5-flash")
        if preferred in {"google", "gemini"} and settings.GOOGLE_API_KEY:
            # GeminiLLMProvider lives with the shared LLM adapters used by
            # requirements extraction. Import it lazily because that module
            # also imports onboarding schemas during application startup.
            from app.services.onboarding.intelligence import GeminiLLMProvider

            return GeminiLLMProvider(settings.GOOGLE_API_KEY), model
        if preferred == "openai" and settings.OPENAI_API_KEY:
            return OpenAILLMProvider(settings.OPENAI_API_KEY), model
        if preferred == "anthropic" and settings.ANTHROPIC_API_KEY:
            return AnthropicLLMProvider(settings.ANTHROPIC_API_KEY), model
        # Respect the preferred provider. Do not silently switch providers
        # for onboarding when the user has not configured one.
        return None, model

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
    def _parse_response(content: str) -> OnboardingModelResponse:
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end < start:
            raise ValueError("Onboarding model did not return JSON")
        value = json.loads(cleaned[start : end + 1])
        if not isinstance(value, dict):
            raise ValueError("Onboarding model response must be an object")
        intent = value.get("proposed_intent")
        if intent not in ConfiguredOnboardingModelProvider._ALLOWED_INTENTS:
            raise ValueError("Onboarding model returned an unsupported intent")
        text = value.get("text")
        proposed_data = value.get("proposed_data", {})
        suggested_actions = value.get("suggested_actions", [])
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Onboarding model response has no text")
        if not isinstance(proposed_data, dict):
            raise ValueError("Onboarding model proposed_data must be an object")
        if not isinstance(suggested_actions, list) or not all(isinstance(item, str) for item in suggested_actions):
            raise ValueError("Onboarding model suggested_actions must be strings")

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

        unsupported = normalized_data.get("unsupported_integrations", [])
        coming_soon = normalized_data.get("coming_soon_integrations", [])
        if isinstance(unsupported, list) or isinstance(coming_soon, list):
            unsupported_names = [item.strip() for item in unsupported if isinstance(item, str) and item.strip()] if isinstance(unsupported, list) else []
            coming_soon_names = [item.strip() for item in coming_soon if isinstance(item, str) and item.strip()] if isinstance(coming_soon, list) else []
            notices: list[str] = []
            if unsupported_names:
                notices.append(
                    f"{', '.join(unsupported_names)} is not supported by Zyntry yet."
                )
            if coming_soon_names:
                notices.append(
                    f"{', '.join(coming_soon_names)} is coming soon and is not available for this runtime yet."
                )
            if notices:
                text = (
                    "\n\n".join(notices)
                    + "\n\nI left those sources out of the runtime draft. "
                    "Would you like to continue with the supported integrations, "
                    "or describe another source?\n\n"
                    + text.strip()
                )
        return OnboardingModelResponse(
            text=text.strip(),
            proposed_intent=intent,
            proposed_data=normalized_data,
            suggested_actions=[item.strip() for item in suggested_actions if item.strip()][:8],
        )

    async def generate_step_response(
        self,
        user_message: str,
        current_state: str,
        current_config: dict[str, Any],
        history: list[dict[str, Any]],
    ) -> OnboardingModelResponse:
        provider, model = self._provider()
        if provider is None:
            return await self.fallback.generate_step_response(
                user_message, current_state, current_config, history
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
intents), proposed_data (safe configuration changes), and suggested_actions
(zero to eight short choices). Never include credentials, secrets, private
data, hidden reasoning, or markdown outside the JSON object.

If the user requests a connector that is not in the manifest, put its name in
proposed_data.unsupported_integrations. If it is marked coming_soon or
disabled, put its name in proposed_data.coming_soon_integrations. Do not put
either kind in proposed_data.integrations; explain that it was left out and
ask whether the user wants to continue with available sources.

Ask a focused clarification question when the requirements extractor has not
captured enough information. Never execute provisioning or a write action
unless the user has explicitly confirmed it. For company data versus
end-user OAuth, preserve the ownership stated by the user. Runtime creation
stores a draft; project attachment and connector authorization happen later.
"""
        payload = {
            "current_state": current_state,
            "current_config": self._safe_config(current_config),
            "recent_conversation": history[-12:],
            "latest_message": user_message,
            "capability_manifest": self._capability_manifest(),
            "allowed_intents": sorted(self._ALLOWED_INTENTS),
        }
        try:
            content, _ = await provider.generate(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(payload, default=str)},
                ],
                model=model,
                max_tokens=1400,
                temperature=0.25,
            )
            return self._parse_response(content)
        except Exception:
            logger.exception("Onboarding conversational model failed; using fallback provider")
            return await self.fallback.generate_step_response(
                user_message, current_state, current_config, history
            )

    def _extract_runtime_name(self, message: str) -> str | None:
        """Keep the engine's name extraction compatible with the fallback."""
        return self.fallback._extract_runtime_name(message)


default_onboarding_model_provider = ConfiguredOnboardingModelProvider()


