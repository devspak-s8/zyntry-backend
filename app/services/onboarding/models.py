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

            # If user already explicitly stated their architecture in the first prompt
            if has_user_connect and not has_company_data:
                mode = "end_user_oauth"
            elif has_company_data and not has_user_connect:
                mode = "zyntry_managed"
            elif has_user_connect and has_company_data:
                mode = "hybrid"
            else:
                mode = None

            if mode:
                # Mode is known, ask for services
                arch_desc = "allow your users to connect their own accounts" if mode == "end_user_oauth" else "connect directly to your company data"
                return OnboardingModelResponse(
                    text=(
                        f"Nice. Building a **{use_case.replace('_', ' ').title()}** that will {arch_desc}.\n\n"
                        "Which services or external integrations should your application support? "
                        "(e.g., GitHub, Slack, Notion, PostgreSQL, MongoDB, Gmail)"
                    ),
                    proposed_intent="set_use_case_and_mode",
                    proposed_data={
                        "use_case": use_case,
                        "application_type": "customer_facing_ai_app" if mode == "end_user_oauth" else "internal_ai_agent",
                        "integration_mode": mode,
                        "integrations": detected_integrations,
                        "capabilities": {slug: self._default_capabilities(slug) for slug in detected_integrations},
                    },
                    suggested_actions=["GitHub", "Slack", "Notion", "PostgreSQL", "MongoDB", "Gmail"],
                )

            return OnboardingModelResponse(
                text=(
                    "Nice. What should the agent have access to?\n\n"
                    "For example, it could work with your company's data, connect to services like "
                    "GitHub, Slack or Notion, search documents, query databases, or allow your users to connect their own accounts."
                ),
                proposed_intent="set_use_case",
                proposed_data={"use_case": use_case},
                suggested_actions=[
                    "Company data",
                    "My users' accounts",
                    "Both",
                    "Not sure yet",
                ],
            )

        # -------------------------------------------------------------
        # 2. State: discovering_application_type / discovering_use_case
        # -------------------------------------------------------------
        if current_state in ("discovering_use_case", "discovering_application_type"):
            detected_integrations = self._detect_integrations(msg_lower)

            # Check if user clarified their use case instead
            if any(k in msg_lower for k in ["agent", "engineer", "triage", "support", "bot", "assistant", "saas"]):
                refined_use_case = self._extract_use_case(msg_lower)
                config["use_case"] = refined_use_case

            if "company" in msg_lower or "internal" in msg_lower or "mode a" in msg_lower:
                mode = "zyntry_managed"
                app_type = "internal_ai_agent"
                desc = "Your runtime will connect directly to your company's data sources and workspaces."
            elif "both" in msg_lower or "hybrid" in msg_lower:
                mode = "hybrid"
                app_type = "hybrid_ai_app"
                desc = "Your runtime will support both company-level data connections and individual end-user accounts."
            elif any(k in msg_lower for k in ["user", "users", "their own", "byo", "mode b"]):
                mode = "end_user_oauth"
                app_type = "customer_facing_ai_app"
                desc = "Your runtime will allow each user of your application to connect their own services."
            else:
                # If they didn't specify architecture, prompt them again nicely
                use_case_title = config.get("use_case", "AI Agent").replace("_", " ").title()
                integ_hint = f" with **{', '.join(slug.title() for slug in detected_integrations)}**" if detected_integrations else ""
                return OnboardingModelResponse(
                    text=(
                        f"Got it! Designing a **{use_case_title}**{integ_hint}.\n\n"
                        "Should this runtime work with your **company's own internal data**, or will your **users connect their own accounts**?"
                    ),
                    proposed_intent="set_use_case",
                    proposed_data={
                        "use_case": config.get("use_case", "general_ai_application"),
                        "integrations": detected_integrations,
                    },
                    suggested_actions=["Company data", "My users' accounts", "Both", "Not sure yet"],
                )

            if detected_integrations:
                caps = {slug: self._default_capabilities(slug) for slug in detected_integrations}
                integ_names = " and ".join(slug.title() for slug in detected_integrations)
                return OnboardingModelResponse(
                    text=(
                        f"Got it. {desc}\n\n"
                        f"I've selected **{integ_names}** for your runtime.\n\n"
                        "Which services should your application support?"
                    ),
                    proposed_intent="set_application_type",
                    proposed_data={
                        "application_type": app_type,
                        "integration_mode": mode,
                        "integrations": detected_integrations,
                        "capabilities": caps,
                    },
                    suggested_actions=["GitHub", "Slack", "Notion", "PostgreSQL", "MongoDB", "Gmail"],
                )

            return OnboardingModelResponse(
                text=(
                    f"Got it. {desc}\n\n"
                    "Which services should your application support?"
                ),
                proposed_intent="set_application_type",
                proposed_data={"application_type": app_type, "integration_mode": mode},
                suggested_actions=["GitHub", "Slack", "Notion", "PostgreSQL", "MongoDB", "Gmail"],
            )

        # -------------------------------------------------------------
        # 3. State: selecting_integrations / selecting_capabilities
        # -------------------------------------------------------------
        if current_state in ("selecting_integrations", "selecting_capabilities"):
            detected_integrations = self._detect_integrations(msg_lower)
            if not detected_integrations and config.get("integrations"):
                detected_integrations = config["integrations"]
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

            integ_names = ", ".join(slug.title() for slug in detected_integrations)
            return OnboardingModelResponse(
                text=(
                    f"Configured **{integ_names}** with standard search and retrieval capabilities.\n\n"
                    "What matters most for your AI runtime?\n"
                    "**Fast responses**, **balanced performance**, or **maximum intelligence**?"
                ),
                proposed_intent="select_integrations",
                proposed_data={
                    "integrations": detected_integrations,
                    "capabilities": caps,
                },
                suggested_actions=["Fast responses", "Balanced performance", "Maximum intelligence"],
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
                suggested_actions=["Confirm & Create Runtime", "Change something"],
            )

        # Fallback
        return OnboardingModelResponse(
            text="Understood. Updating your runtime design with your preferences.",
            proposed_intent="general_update",
            proposed_data={},
            suggested_actions=["Confirm & Create Runtime", "Continue"],
        )

    def _extract_use_case(self, msg: str) -> str:
        if "support" in msg or "customer" in msg:
            return "ai_customer_support"
        if "triage" in msg or "engineer" in msg or "issue" in msg:
            return "autonomous_issue_triage_agent"
        if "code" in msg or "developer" in msg:
            return "developer_ai_assistant"
        if "rag" in msg or "knowledge" in msg or "search" in msg:
            return "knowledge_search_rag"
        if "agent" in msg:
            return "autonomous_ai_agent"
        if "saas" in msg:
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
        return list(dict.fromkeys(found))

    def _default_capabilities(self, slug: str) -> list[str]:
        defn = integration_registry.get(slug)
        if defn:
            return [c.slug for c in defn.capabilities if not c.is_write]
        return []

    def _extract_strategy(self, msg: str) -> str:
        if "fast" in msg or "speed" in msg or "router" in msg:
            return "latency_optimized"
        if "intel" in msg or "max" in msg or "best" in msg:
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
        arch_title = "End-user connections" if integration_mode == "end_user_oauth" else "Zyntry-managed connections" if integration_mode == "zyntry_managed" else "Hybrid connections"
        runtime_title = f"{use_case.replace('_', ' ').title()} Agent"

        integ_sections = []
        for slug in integrations:
            caps = capabilities.get(slug, self._default_capabilities(slug))
            cap_lines = "\n".join(f"* {c.replace('_', ' ').capitalize()}" for c in caps) if caps else "* Standard read operations"
            integ_sections.append(f"**{slug.title()}**\n{cap_lines}")

        integ_block = "\n\n".join(integ_sections) if integ_sections else "* None configured"

        notice = (
            "Your users will connect their own external accounts when using your application. "
            "Zyntry will not have access to those accounts until they authorize the connection."
            if integration_mode == "end_user_oauth"
            else "Zyntry will connect directly to your specified workspace or data source."
        )

        return (
            "**Here's what I've configured for you.**\n\n"
            f"**Runtime**\n{runtime_title}\n\n"
            f"**Purpose**\n{use_case.replace('_', ' ').title()}\n\n"
            f"**Integration architecture**\n{arch_title}\n\n"
            f"**Integrations**\n{integ_block}\n\n"
            f"**Routing**\n{routing_strategy.replace('_', ' ').capitalize()} automatic routing\n\n"
            f"**Environment**\n{environment.capitalize()}\n\n"
            f"{notice}"
        )


default_onboarding_model_provider = FastOnboardingModelProvider()
