from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.services.integrations.definitions import integration_registry


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
                    text="Provisioning your Zyntry runtime now...",
                    proposed_intent="execute_provisioning",
                    proposed_data={},
                    suggested_actions=["Generate API Key", "Go to Runtime Console"],
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
    ) -> str:
        uc_title = self._use_case_title(use_case)
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
            "Ready to provision this runtime."
        )


default_onboarding_model_provider = FastOnboardingModelProvider()


