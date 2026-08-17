from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.models.onboarding_session import OnboardingSession
from app.models.runtimes import Runtime
from app.repositories import UnitOfWork
from app.schemas.integrations import RuntimeIntegrationCreate
from app.schemas.onboarding_chat import (
    OnboardingCompleteRequest,
    OnboardingCompleteResponse,
    OnboardingMessageRequest,
    OnboardingMessageResponse,
)
from app.services.integrations.definitions import integration_registry
from app.services.integrations.service import IntegrationService
from app.services.onboarding.models import OnboardingModelProvider, default_onboarding_model_provider

logger = logging.getLogger(__name__)

VALID_STATES = [
    "onboarding_started",
    "discovering_use_case",
    "discovering_application_type",
    "selecting_integrations",
    "selecting_capabilities",
    "configuring_runtime",
    "confirming_configuration",
    "provisioning",
    "completed",
]


class OnboardingEngine:
    def __init__(
        self,
        uow: UnitOfWork,
        model_provider: OnboardingModelProvider | None = None,
    ) -> None:
        self.uow = uow
        self.model_provider = model_provider or default_onboarding_model_provider
        self.integration_service = IntegrationService(uow)

    async def get_or_create_session(
        self, user_id: UUID, initial_prompt: str | None = None, reset: bool = False
    ) -> OnboardingSession:
        if reset:
            await self.uow.onboarding_sessions.cancel_all_active_by_user(user_id)
            await self.uow.commit()

        session = await self.uow.onboarding_sessions.get_latest_active_by_user(user_id)
        if session and not reset:
            return session

        welcome_msg = {
            "role": "assistant",
            "content": (
                "**Let's build your Zyntry runtime.**\n\n"
                "Tell me what you're building, what you want it to do, or what you want Zyntry to handle for you."
            ),
            "timestamp": datetime.now(UTC).isoformat(),
        }
        messages = [welcome_msg]

        if initial_prompt:
            messages.append({
                "role": "user",
                "content": initial_prompt,
                "timestamp": datetime.now(UTC).isoformat(),
            })
            ai_resp = await self.model_provider.generate_step_response(
                user_message=initial_prompt,
                current_state="onboarding_started",
                current_config={},
                history=messages,
            )
            config, next_state = self._authorize_and_transition(
                current_state="onboarding_started",
                current_config={},
                proposed_intent=ai_resp.proposed_intent,
                proposed_data=ai_resp.proposed_data,
            )
            messages.append({
                "role": "assistant",
                "content": ai_resp.text,
                "timestamp": datetime.now(UTC).isoformat(),
                "proposed_intent": ai_resp.proposed_intent,
            })
            state = next_state
        else:
            state = "onboarding_started"
            config = {}

        session = await self.uow.onboarding_sessions.create(
            user_id=user_id,
            state=state,
            messages=messages,
            configuration=config,
        )
        await self.uow.commit()
        return session

    async def process_message(
        self, user_id: UUID, req: OnboardingMessageRequest
    ) -> OnboardingMessageResponse:
        session_uuid = UUID(req.session_id)
        session = await self.uow.onboarding_sessions.get(session_uuid)
        if session is None or session.user_id != user_id:
            raise ValueError("Onboarding session not found")

        if session.state == "completed":
            return OnboardingMessageResponse(
                session_id=str(session.id),
                response="This onboarding session has already been completed. Your runtime is active and ready!",
                state="completed",
                configuration=session.configuration,
                is_complete=True,
                suggested_actions=["Generate API Key", "Go to Runtime Console"],
                proposed_runtime=session.configuration,
            )

        # Append user message
        messages = list(session.messages or [])
        messages.append({
            "role": "user",
            "content": req.message,
            "timestamp": datetime.now(UTC).isoformat(),
        })

        current_config = dict(session.configuration or {})

        # Step 1: LLM interprets user message and proposes actions
        ai_resp = await self.model_provider.generate_step_response(
            user_message=req.message,
            current_state=session.state,
            current_config=current_config,
            history=messages,
        )

        # Step 2: Check for direct execution / confirmation
        msg_lower = req.message.lower().strip()
        is_confirmation = (
            ai_resp.proposed_intent == "execute_provisioning"
            or (session.state in ("confirming_configuration", "configuring_runtime") and any(
                k in msg_lower for k in ["confirm", "create runtime", "create", "yes", "looks good", "let's do it", "provision", "proceed"]
            ))
        )

        if is_confirmation:
            # Auto-provision the runtime directly and complete session
            complete_res = await self.complete_onboarding(
                user_id=user_id,
                req=OnboardingCompleteRequest(session_id=str(session.id)),
            )
            completion_text = complete_res.message
            messages.append({
                "role": "assistant",
                "content": completion_text,
                "timestamp": datetime.now(UTC).isoformat(),
                "proposed_intent": "completed",
            })
            await self.uow.onboarding_sessions.update(session, messages=messages)
            await self.uow.commit()

            return OnboardingMessageResponse(
                session_id=str(session.id),
                response=completion_text,
                state="completed",
                configuration=session.configuration,
                is_complete=True,
                suggested_actions=["Generate API Key", "Go to Runtime Console"],
                proposed_runtime={
                    "runtime_id": complete_res.runtime_id,
                    "runtime_name": complete_res.runtime_name,
                    "status": complete_res.status,
                    "environment": complete_res.environment,
                    "enabled_integrations": complete_res.enabled_integrations,
                },
            )

        # Step 3: Backend Authorizes & Validates LLM Proposals
        validated_config, next_state = self._authorize_and_transition(
            current_state=session.state,
            current_config=current_config,
            proposed_intent=ai_resp.proposed_intent,
            proposed_data=ai_resp.proposed_data,
        )

        # Append assistant response
        messages.append({
            "role": "assistant",
            "content": ai_resp.text,
            "timestamp": datetime.now(UTC).isoformat(),
            "proposed_intent": ai_resp.proposed_intent,
        })

        await self.uow.onboarding_sessions.update(
            session,
            state=next_state,
            messages=messages,
            configuration=validated_config,
        )
        await self.uow.commit()

        is_ready_to_provision = next_state in ("confirming_configuration", "provisioning")

        return OnboardingMessageResponse(
            session_id=str(session.id),
            response=ai_resp.text,
            state=next_state,
            configuration=validated_config,
            is_complete=(next_state == "completed"),
            suggested_actions=ai_resp.suggested_actions or self.get_suggested_actions_for_state(next_state),
            proposed_runtime=validated_config if is_ready_to_provision else None,
        )

    def _authorize_and_transition(
        self,
        current_state: str,
        current_config: dict[str, Any],
        proposed_intent: str | None,
        proposed_data: dict[str, Any],
    ) -> tuple[dict[str, Any], str]:
        """Backend authorization: strictly validate proposed changes and compute next state."""
        config = dict(current_config)

        if proposed_intent == "set_use_case":
            config["use_case"] = proposed_data.get("use_case", "general_ai_application")
            if "integrations" in proposed_data and proposed_data["integrations"]:
                config["integrations"] = proposed_data["integrations"]
            return config, "discovering_application_type"

        if proposed_intent == "set_use_case_and_mode":
            config["use_case"] = proposed_data.get("use_case", "general_ai_application")
            config["application_type"] = proposed_data.get("application_type", "customer_facing_ai_app")
            config["integration_mode"] = proposed_data.get("integration_mode", "end_user_oauth")
            if "integrations" in proposed_data and proposed_data["integrations"]:
                config["integrations"] = proposed_data["integrations"]
            if "capabilities" in proposed_data and proposed_data["capabilities"]:
                config["capabilities"] = proposed_data["capabilities"]
            return config, "selecting_integrations"

        if proposed_intent == "set_application_type":
            mode = proposed_data.get("integration_mode", "zyntry_managed")
            if mode not in ("zyntry_managed", "end_user_oauth", "hybrid"):
                mode = "zyntry_managed"
            config["application_type"] = proposed_data.get("application_type", "customer_facing_ai_app")
            config["integration_mode"] = mode
            if "integrations" in proposed_data and proposed_data["integrations"]:
                config["integrations"] = proposed_data["integrations"]
            if "capabilities" in proposed_data and proposed_data["capabilities"]:
                config["capabilities"] = proposed_data["capabilities"]
            return config, "selecting_integrations"

        if proposed_intent in ("select_integrations", "quick_bootstrap", "set_application_type_and_integrations"):
            if "use_case" in proposed_data:
                config["use_case"] = proposed_data["use_case"]
            if "application_type" in proposed_data:
                config["application_type"] = proposed_data["application_type"]
            if "integration_mode" in proposed_data:
                config["integration_mode"] = proposed_data["integration_mode"]
            return self._validate_integrations_and_transition(config, proposed_data)

        if proposed_intent == "confirm_configuration":
            config["model"] = proposed_data.get("model", "gpt-4o")
            config["provider"] = proposed_data.get("provider", "openai")
            config["routing_strategy"] = proposed_data.get("routing_strategy", "balanced")
            config["environment"] = proposed_data.get("environment", "development")
            return config, "confirming_configuration"

        if proposed_intent == "modify_settings":
            return config, "configuring_runtime"

        # General update fallback
        for k, v in proposed_data.items():
            if k in ("use_case", "application_type", "integration_mode", "model", "provider", "routing_strategy"):
                config[k] = v

        return config, current_state

    def _validate_integrations_and_transition(
        self, config: dict[str, Any], proposed_data: dict[str, Any]
    ) -> tuple[dict[str, Any], str]:
        raw_integrations = proposed_data.get("integrations", [])
        valid_integrations = []
        valid_capabilities = {}

        for slug in raw_integrations:
            defn = integration_registry.get(slug)
            if defn:
                valid_integrations.append(defn.slug)
                req_caps = proposed_data.get("capabilities", {}).get(defn.slug)
                all_caps = [c.slug for c in defn.capabilities]
                if req_caps:
                    valid_caps = [c for c in req_caps if c in all_caps]
                else:
                    valid_caps = [c.slug for c in defn.capabilities if not c.is_write]
                valid_capabilities[defn.slug] = valid_caps

        config["integrations"] = valid_integrations
        config["capabilities"] = valid_capabilities
        return config, "configuring_runtime"

    def get_suggested_actions_for_state(self, state: str) -> list[str]:
        if state == "onboarding_started":
            return [
                "I'm building an AI customer support agent.",
                "Search our company's GitHub and Slack.",
                "Users connect their own GitHub accounts.",
                "PostgreSQL & Document RAG.",
            ]
        if state in ("discovering_use_case", "discovering_application_type"):
            return ["Company data", "My users' accounts", "Both", "Not sure yet"]
        if state in ("selecting_integrations", "selecting_capabilities"):
            return ["GitHub", "Slack", "Notion", "PostgreSQL", "MongoDB", "Gmail"]
        if state == "configuring_runtime":
            return ["Fast responses", "Balanced performance", "Maximum intelligence"]
        if state == "confirming_configuration":
            return ["Confirm & Create Runtime", "Change something"]
        if state == "completed":
            return ["Generate API Key", "Go to Runtime Console"]
        return ["Continue"]

    async def complete_onboarding(
        self, user_id: UUID, req: OnboardingCompleteRequest
    ) -> OnboardingCompleteResponse:
        session_uuid = UUID(req.session_id)
        session = await self.uow.onboarding_sessions.get(session_uuid)
        if session is None or session.user_id != user_id:
            raise ValueError("Onboarding session not found")

        # If already provisioned, return existing
        if session.state == "completed" and session.created_runtime_id:
            existing_rt = await self.uow.runtimes.get(session.created_runtime_id)
            if existing_rt:
                return OnboardingCompleteResponse(
                    session_id=str(session.id),
                    runtime_id=str(existing_rt.id),
                    runtime_name=existing_rt.name,
                    environment=existing_rt.environment,
                    status=existing_rt.status,
                    enabled_integrations=[],
                    message="Runtime already provisioned and ready.",
                )

        config = session.configuration or {}
        runtime_name = req.runtime_name or f"{config.get('use_case', 'AI App').replace('_', ' ').title()} Runtime"
        env = req.environment or config.get("environment", "development")

        # 1. Create user-first Runtime (user_id NOT NULL, org/project NULL)
        runtime = await self.uow.runtimes.create(
            user_id=user_id,
            name=runtime_name,
            environment=env,
            provider=config.get("provider", "openai"),
            model=config.get("model", "gpt-4o"),
            routing_strategy=config.get("routing_strategy", "balanced"),
            embedding_model="text-embedding-3-small",
            vector_store="pgvector",
            chunk_size=512,
            chunk_overlap=64,
            status="active",
            health=100.0,
            config=config,
        )
        await self.uow.commit()

        # 2. Configure Runtime Integrations (Separate capability from connection)
        enabled_integrations_list: list[dict[str, Any]] = []
        integrations = config.get("integrations", [])
        capabilities_map = config.get("capabilities", {})
        integration_mode = config.get("integration_mode", "zyntry_managed")

        for slug in integrations:
            defn = integration_registry.get(slug)
            if defn is None:
                continue

            caps = capabilities_map.get(slug, [c.slug for c in defn.capabilities if not c.is_write])
            mode = integration_mode
            if mode not in defn.supported_connection_modes:
                mode = defn.supported_connection_modes[0] if defn.supported_connection_modes else "zyntry_managed"

            ri = await self.integration_service.enable_runtime_integration(
                runtime_id=runtime.id,
                data=RuntimeIntegrationCreate(
                    integration_slug=slug,
                    connection_mode=mode,
                    enabled_capabilities=caps,
                    config={"onboarded": True},
                ),
            )
            enabled_integrations_list.append({
                "integration_slug": slug,
                "connection_mode": mode,
                "enabled_capabilities": caps,
                "connection_status": ri.connection_status,
            })

        # 3. Mark session completed (API Key generation is decoupled and user-requested)
        await self.uow.onboarding_sessions.update(
            session,
            state="completed",
            created_runtime_id=runtime.id,
            completed_at=datetime.now(UTC),
        )
        await self.uow.commit()

        integs_formatted = "\n".join(
            f"* **{item['integration_slug'].title()}**: {', '.join(c.replace('_', ' ').capitalize() for c in item['enabled_capabilities'])}"
            for item in enabled_integrations_list
        ) if enabled_integrations_list else "* Standard read operations"

        message_markdown = (
            "### 🚀 Your Zyntry Runtime is Ready!\n\n"
            f"**Runtime Name:** {runtime.name}\n\n"
            f"**Status:** 🟢 Active\n\n"
            f"**Environment:** {runtime.environment.capitalize()}\n\n"
            f"**Routing Strategy:** {runtime.routing_strategy.replace('_', ' ').capitalize()} Automatic Routing\n\n"
            "#### Enabled Integrations & Capabilities:\n"
            f"{integs_formatted}\n\n"
            "---\n\n"
            "#### 📌 Next Step:\n"
            "Generate an API key to connect your application and start invoking your runtime."
        )

        return OnboardingCompleteResponse(
            session_id=str(session.id),
            runtime_id=str(runtime.id),
            runtime_name=runtime.name,
            environment=runtime.environment,
            status=runtime.status,
            enabled_integrations=enabled_integrations_list,
            message=message_markdown,
        )
