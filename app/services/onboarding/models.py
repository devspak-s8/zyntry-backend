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

    # Slug -> human-readable display name
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

    # Use-case slug -> human-readable title
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
        """Return a contextual follow-up question + suggested actions based on the detected use case."""
        if use_case == "autonomous_issue_triage_agent":
            return (
                "What data sources should your triage agent work with?\n\n"
                "For example, it could pull issues from GitHub, post updates to Slack, "
                "reference internal docs, or query a database for context.",
                [
                    "GitHub issues and pull requests",
                    "GitHub, Slack, and our internal docs",
                    "GitHub and our PostgreSQL database",
                    "Not sure yet — help me decide",
                ],
            )
        if use_case == "ai_customer_support":
            return (
                "What should your support agent have access to?\n\n"
                "It could search your knowledge base, reference Notion docs, "
                "pull customer data from a database, or send updates via Slack.",
                [
                    "Our knowledge base and documentation",
                    "PostgreSQL customer data and Notion docs",
                    "Slack, email, and uploaded support docs",
                    "Not sure yet — help me decide",
                ],
            )
        if use_case == "developer_ai_assistant":
            return (
                "What tools should your dev assistant connect to?\n\n"
                "It could browse repositories, search Slack discussions, "
                "query databases, or reference internal documentation.",
                [
                    "GitHub repos and Slack channels",
                    "GitHub, Notion wiki, and PostgreSQL",
                    "All our dev tools — GitHub, Slack, Notion",
                    "Not sure yet — help me decide",
                ],
            )
        if use_case == "knowledge_search_rag":
            return (
                "Where does your knowledge live?\n\n"
                "Your RAG system can index uploaded documents, Notion pages, "
                "database records, S3 files, or crawled websites.",
                [
                    "Uploaded PDFs and internal documentation",
                    "Notion pages and PostgreSQL records",
                    "Our website and uploaded documents",
                    "Not sure yet — help me decide",
                ],
            )
        # Generic fallback
        return (
            "What data sources and tools should your runtime connect to?\n\n"
            "For example: GitHub for code, Slack for conversations, "
            "PostgreSQL for structured data, or uploaded documents for RAG.",
            [
                "GitHub and Slack",
                "PostgreSQL and uploaded documents",
                "Notion, GitHub, and Slack",
                "Not sure yet — help me decide",
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

        # Check for direct confirmation in any late state
        if current_state in ("confirming_configuration", "configuring_runtime"):
            if any(k in msg_lower for k in ["confirm", "create", "yes", "looks good", "let's do it", "provision", "proceed"]):
                return OnboardingModelResponse(
                    text="Provisioning your Zyntry runtime now...",
                    proposed_intent="execute_provisioning",
                    proposed_data={},
                    suggested_actions=["Generate API Key", "Go to Runtime Console"],
                )

        # -------------------------------------------------------------
        # 1. State: onboarding_started -> Extract Use Case & Purpose
        # -------------------------------------------------------------
        if current_state == "onboarding_started":
            use_case = self._extract_use_case(msg_lower)
            detected_integrations = self._detect_integrations(msg_lower)
            has_user_connect = any(k in msg_lower for k in ["their own", "users connect", "user connect", "users' accounts", "byo", "mode b"])
            has_company_data = any(k in msg_lower for k in ["company data", "our company", "company's data", "internal data", "mode a"])
            uc_title = self._use_case_title(use_case)

            # If user explicitly stated architecture in the first prompt
            if has_user_connect and not has_company_data:
                mode = "end_user_oauth"
            elif has_company_data and not has_user_connect:
                mode = "zyntry_managed"
            elif has_user_connect and has_company_data:
                mode = "hybrid"
            else:
                mode = None

            if mode:
                arch_desc = "allow your users to connect their own accounts" if mode == "end_user_oauth" else "connect directly to your company data"
                integ_hint = f" with **{self._display_names_list(detected_integrations)}**" if detected_integrations else ""

                question, actions = self._context_aware_integration_question(use_case)
                return OnboardingModelResponse(
                    text=(
                        f"Great — building a **{uc_title}**{integ_hint} that will {arch_desc}.\n\n"
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

            # No architecture specified — ask about data access pattern
            if detected_integrations:
                integ_text = self._display_names_list(detected_integrations)
                return OnboardingModelResponse(
                    text=(
                        f"Got it — a **{uc_title}** connected to **{integ_text}**.\n\n"
                        "One quick question: will this runtime access **your company's own data and accounts**, "
                        "or will **your end users connect their own** (e.g., their own GitHub/Slack)?"
                    ),
                    proposed_intent="set_use_case",
                    proposed_data={
                        "use_case": use_case,
                        "integrations": detected_integrations,
                    },
                    suggested_actions=[
                        "Our company's data",
                        "Each user connects their own",
                        "Both",
                        "Not sure yet",
                    ],
                )
            else:
                return OnboardingModelResponse(
                    text=(
                        f"Nice — building a **{uc_title}**.\n\n"
                        "Will this runtime access **your company's own data**, "
                        "or will **your end users connect their own accounts** (like their own GitHub or Slack)?"
                    ),
                    proposed_intent="set_use_case",
                    proposed_data={
                        "use_case": use_case,
                        "integrations": [],
                    },
                    suggested_actions=[
                        "Our company's data",
                        "Each user connects their own",
                        "Both",
                        "Not sure yet",
                    ],
                )

        # -------------------------------------------------------------
        # 2. State: discovering_application_type / discovering_use_case
        # -------------------------------------------------------------
        if current_state in ("discovering_use_case", "discovering_application_type"):
            detected_integrations = self._detect_integrations(msg_lower)
            # Merge with previously-detected integrations so nothing is lost
            existing = list(config.get("integrations", []))
            for slug in existing:
                if slug not in detected_integrations:
                    detected_integrations.append(slug)

            use_case = config.get("use_case", "general_ai_application")
            uc_title = self._use_case_title(use_case)

            # Handle "Not sure yet" or unsure input gracefully without looping
            if "not sure" in msg_lower or "unsure" in msg_lower or "default" in msg_lower or "skip" in msg_lower or "help me" in msg_lower:
                mode = "zyntry_managed"
                app_type = "internal_ai_agent"
                desc = "No problem! We'll default to **Zyntry-managed connections** — your runtime connects directly to your data. You can always enable user-level OAuth later."
            elif "company" in msg_lower or "internal" in msg_lower or "our" in msg_lower or "mode a" in msg_lower:
                mode = "zyntry_managed"
                app_type = "internal_ai_agent"
                desc = "Perfect. Your runtime will connect directly to your company's data sources and workspaces."
            elif "both" in msg_lower or "hybrid" in msg_lower:
                mode = "hybrid"
                app_type = "hybrid_ai_app"
                desc = "Got it — hybrid mode. Your runtime will support both company-level connections and individual end-user accounts."
            elif any(k in msg_lower for k in ["user", "users", "their own", "byo", "mode b", "each"]):
                mode = "end_user_oauth"
                app_type = "customer_facing_ai_app"
                desc = "Got it. Each of your users will connect their own accounts — Zyntry handles the OAuth flows for you."
            else:
                # They typed integrations directly instead of choosing architecture
                mode = "zyntry_managed"
                app_type = "internal_ai_agent"
                desc = "Got it — setting up Zyntry-managed connections for your runtime."

            if detected_integrations:
                caps = {slug: self._default_capabilities(slug) for slug in detected_integrations}
                integ_text = self._display_names_list(detected_integrations)

                # Build a contextual capability summary instead of raw slug dump
                cap_summary_parts = []
                for slug in detected_integrations:
                    defn = integration_registry.get(slug)
                    if defn:
                        read_caps = [c for c in defn.capabilities if not c.is_write]
                        if read_caps:
                            cap_summary_parts.append(f"**{self._display_name(slug)}** ({', '.join(c.name.lower() for c in read_caps[:2])})")
                        else:
                            cap_summary_parts.append(f"**{self._display_name(slug)}**")

                cap_summary = ", ".join(cap_summary_parts) if cap_summary_parts else integ_text

                return OnboardingModelResponse(
                    text=(
                        f"{desc}\n\n"
                        f"I've configured {cap_summary} with read-only access by default.\n\n"
                        "Last thing — what matters most for your AI's performance?\n"
                        "Speed, balanced performance, or maximum intelligence?"
                    ),
                    proposed_intent="set_application_type_and_integrations",
                    proposed_data={
                        "application_type": app_type,
                        "integration_mode": mode,
                        "integrations": detected_integrations,
                        "capabilities": caps,
                    },
                    suggested_actions=["Speed — fast responses", "Balanced — best of both", "Max intelligence — highest quality"],
                )

            # No integrations detected — ask about data sources contextually
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

        # -------------------------------------------------------------
        # 3. State: selecting_integrations / selecting_capabilities
        # -------------------------------------------------------------
        if current_state in ("selecting_integrations", "selecting_capabilities"):
            detected_integrations = self._detect_integrations(msg_lower)
            # Merge with previously-detected integrations so nothing is lost
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
                    f"Great — I've set up **{integ_text}** with the standard capabilities for your use case.\n\n"
                    "Now, what matters most for your AI's performance?\n"
                    "Speed, balanced performance, or maximum intelligence?"
                ),
                proposed_intent="select_integrations",
                proposed_data={
                    "integrations": detected_integrations,
                    "capabilities": caps,
                },
                suggested_actions=["Speed — fast responses", "Balanced — best of both", "Max intelligence — highest quality"],
            )

        # -------------------------------------------------------------
        # 4. State: configuring_runtime -> Performance & Environment
        # -------------------------------------------------------------
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
                suggested_actions=["Confirm & Create Runtime", "I want to change something"],
            )

        # Fallback
        return OnboardingModelResponse(
            text="Got it — I've updated your runtime configuration with those preferences.",
            proposed_intent="general_update",
            proposed_data={},
            suggested_actions=["Confirm & Create Runtime", "Continue"],
        )

    def _extract_use_case(self, msg: str) -> str:
        # Strip out example integration stack mentions first
        cleaned = re.sub(r"example integration stack:?.*", "", msg, flags=re.IGNORECASE)
        cleaned = re.sub(r"example integrations:?.*", "", cleaned, flags=re.IGNORECASE).strip()

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
        found = []
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
            if "postgres" not in found:
                found.append("postgres")
        if "mongo" in msg:
            if "mongodb" not in found:
                found.append("mongodb")
        if "gmail" in msg or "mail" in msg:
            if "gmail" not in found:
                found.append("gmail")
        # Detect document upload / RAG as a document_storage capability
        if any(k in msg for k in ["document", "documentation", "upload", "docs", "pdf", "rag"]):
            if "document_storage" not in found:
                found.append("document_storage")
        return list(dict.fromkeys(found))

    def _default_capabilities(self, slug: str) -> list[str]:
        defn = integration_registry.get(slug)
        if defn:
            return [c.slug for c in defn.capabilities if not c.is_write]
        return []

    def _extract_strategy(self, msg: str) -> str:
        if "fast" in msg or "speed" in msg or "router" in msg:
            return "latency_optimized"
        if "intel" in msg or "max" in msg or "best" in msg or "highest" in msg:
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
            "latency_optimized": "⚡ Speed-optimized",
            "quality_optimized": "🧠 Maximum intelligence",
            "balanced": "⚖️ Balanced",
        }
        strategy_label = strategy_labels.get(routing_strategy, routing_strategy.replace("_", " ").capitalize())

        arch_labels = {
            "end_user_oauth": "End-user OAuth — each user connects their own accounts",
            "zyntry_managed": "Zyntry-managed — your company's data and credentials",
            "hybrid": "Hybrid — company data + end-user accounts",
        }
        arch_label = arch_labels.get(integration_mode, integration_mode.replace("_", " ").capitalize())

        integ_sections = []
        for slug in integrations:
            display = self._display_name(slug)
            caps = capabilities.get(slug, self._default_capabilities(slug))
            if caps:
                cap_names = []
                defn = integration_registry.get(slug)
                if defn:
                    cap_map = {c.slug: c.name for c in defn.capabilities}
                    cap_names = [cap_map.get(c, c.replace("_", " ").capitalize()) for c in caps]
                else:
                    cap_names = [c.replace("_", " ").capitalize() for c in caps]
                integ_sections.append(f"  * **{display}** — {', '.join(cap_names)}")
            else:
                integ_sections.append(f"  * **{display}** — Standard read access")

        integ_block = "\n".join(integ_sections) if integ_sections else "  * None configured yet"

        return (
            "### 📋 Here's your runtime configuration:\n\n"
            f"**Runtime:** {uc_title} Runtime\n\n"
            f"**Architecture:** {arch_label}\n\n"
            f"**Routing:** {strategy_label} automatic routing\n\n"
            f"**Environment:** {environment.capitalize()}\n\n"
            f"**Connected Services:**\n{integ_block}\n\n"
            "---\n\n"
            "Does this look right? I'll create your runtime and you'll be ready to generate an API key."
        )


default_onboarding_model_provider = FastOnboardingModelProvider()

