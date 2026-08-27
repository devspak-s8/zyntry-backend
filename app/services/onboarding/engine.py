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
from app.schemas.onboarding_intelligence import ApplicationRequirements
from app.services.integrations.definitions import integration_registry
from app.services.integrations.service import IntegrationService
from app.services.onboarding.intelligence import (
    AdaptiveClarificationService,
    ModelBackedRequirementsExtractor,
    RuntimePlanGenerator,
)
from app.services.onboarding.models import (
    OnboardingModelProvider,
    OnboardingModelResponse,
    default_onboarding_model_provider,
)

logger = logging.getLogger(__name__)

VALID_STATES = [
    "onboarding_started",
    "discovering_use_case",
    "discovering_application_type",
    "clarifying_requirements",
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
        self.requirements_extractor = ModelBackedRequirementsExtractor()
        self.clarification_service = AdaptiveClarificationService()
        self.runtime_plan_generator = RuntimePlanGenerator()

    async def get_or_create_session(
        self, user_id: UUID, initial_prompt: str | None = None, reset: bool = False
    ) -> OnboardingSession:
        if reset:
            await self.uow.onboarding_sessions.cancel_all_active_by_user(user_id)
            await self.uow.commit()

        # Onboarding is for accounts that do not have a runtime yet. Runtime
        # creation starts at ``preconfigured`` because it still needs project
        # resources, but that is not a reason to send an existing user back
        # through first-time onboarding.
        existing_runtime = await self.uow.runtimes.get_latest_by_user(user_id)
        if existing_runtime and not reset:
            session = await self.uow.onboarding_sessions.get_latest_active_by_user(user_id)
            if session:
                session = await self.uow.onboarding_sessions.update(
                    session,
                    state="completed",
                    created_runtime_id=existing_runtime.id,
                    configuration={
                        **(session.configuration or {}),
                        "runtime_id": str(existing_runtime.id),
                        "runtime_name": existing_runtime.name,
                        "runtime_status": existing_runtime.status,
                    },
                    completed_at=datetime.now(UTC),
                )
                await self.uow.commit()
                return session

            latest_session = await self.uow.onboarding_sessions.get_latest_by_user(user_id)
            if latest_session and latest_session.state == "completed":
                return latest_session

            session = await self.uow.onboarding_sessions.create(
                user_id=user_id,
                state="completed",
                messages=[],
                configuration={
                    "runtime_id": str(existing_runtime.id),
                    "runtime_name": existing_runtime.name,
                    "runtime_status": existing_runtime.status,
                },
                created_runtime_id=existing_runtime.id,
                completed_at=datetime.now(UTC),
            )
            await self.uow.commit()
            return session

        session = await self.uow.onboarding_sessions.get_latest_active_by_user(user_id)
        if session and not reset:
            return session

        welcome_msg = {
            "role": "assistant",
            "content": (
                "Tell me what kind of AI application you are building, "
                "or what tools and data sources you want Zyntry to manage."
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
            ai_resp, _ = await self._apply_requirements_intelligence(
                ai_resp=ai_resp,
                message=initial_prompt,
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
            config = self._attach_runtime_plan(config, previous_plan=None)
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
            msg_lower = req.message.lower().strip()
            rt_id = str(session.created_runtime_id) if session.created_runtime_id else None
            runtime_name = session.configuration.get("use_case", "AI App").replace("_", " ").title() + " Runtime"
            if any(k in msg_lower for k in ["console", "dashboard", "runtime", "view"]):
                return OnboardingMessageResponse(
                    session_id=str(session.id),
                    response=f"Your runtime '{runtime_name}' is active. Redirecting to the runtime console.",
                    state="completed",
                    configuration=session.configuration,
                    is_complete=True,
                    suggested_actions=["Generate API Key", "Go to Runtime Console"],
                    proposed_runtime={
                        "runtime_id": rt_id,
                        "action": "navigate_console",
                        "redirect_url": f"/runtimes/{rt_id}" if rt_id else "/runtimes",
                    },
                    application_requirements=session.configuration.get("application_requirements"),
                    runtime_plan=session.configuration.get("runtime_plan"),
                )
            if any(k in msg_lower for k in ["api key", "key", "generate"]):
                return OnboardingMessageResponse(
                    session_id=str(session.id),
                    response=f"Your runtime '{runtime_name}' is active. Redirecting to generate API keys.",
                    state="completed",
                    configuration=session.configuration,
                    is_complete=True,
                    suggested_actions=["Generate API Key", "Go to Runtime Console"],
                    proposed_runtime={
                        "runtime_id": rt_id,
                        "action": "navigate_apikeys",
                        "redirect_url": "/apikeys",
                    },
                    application_requirements=session.configuration.get("application_requirements"),
                    runtime_plan=session.configuration.get("runtime_plan"),
                )
            return OnboardingMessageResponse(
                session_id=str(session.id),
                response="Your runtime is active and ready. Select an action below to view the console or generate an API key.",
                state="completed",
                configuration=session.configuration,
                is_complete=True,
                suggested_actions=["Generate API Key", "Go to Runtime Console"],
                proposed_runtime={
                    "runtime_id": rt_id,
                    "redirect_url": f"/runtimes/{rt_id}" if rt_id else "/runtimes",
                },
                application_requirements=session.configuration.get("application_requirements"),
                runtime_plan=session.configuration.get("runtime_plan"),
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
        ai_resp, _ = await self._apply_requirements_intelligence(
            ai_resp=ai_resp,
            message=req.message,
            current_state=session.state,
            current_config=current_config,
            history=messages,
        )
        # Preserve an explicit name embedded in a natural-language onboarding
        # message even when the message also contains a long capability list.
        extractor = getattr(self.model_provider, "_extract_runtime_name", None)
        runtime_name = extractor(req.message) if callable(extractor) else None
        if runtime_name:
            ai_resp.proposed_data = {
                **ai_resp.proposed_data,
                "runtime_name": runtime_name,
            }

        # Step 2: Check for direct execution / confirmation
        msg_lower = req.message.lower().strip()
        is_confirmation = (
            ai_resp.proposed_intent == "execute_provisioning"
            or (session.state in ("confirming_configuration", "configuring_runtime") and any(
                k in msg_lower for k in ["confirm", "create runtime", "create", "yes", "looks good", "let's do it", "provision", "proceed"]
            ))
        )

        if is_confirmation:
            # Save the configuration draft and complete onboarding. Provisioning
            # happens later when the user creates a project in the console.
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
                suggested_actions=["Create Project", "Review Configuration"],
                proposed_runtime={
                    "runtime_id": complete_res.runtime_id,
                    "runtime_name": complete_res.runtime_name,
                    "status": complete_res.status,
                    "environment": complete_res.environment,
                    "enabled_integrations": complete_res.enabled_integrations,
                },
                application_requirements=complete_res.application_requirements,
                runtime_plan=complete_res.runtime_plan,
                clarification_question=None,
            )

        # Step 3: Backend Authorizes & Validates LLM Proposals
        validated_config, next_state = self._authorize_and_transition(
            current_state=session.state,
            current_config=current_config,
            proposed_intent=ai_resp.proposed_intent,
            proposed_data=ai_resp.proposed_data,
        )
        validated_config = self._attach_runtime_plan(
            validated_config,
            previous_plan=current_config.get("runtime_plan"),
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
        clarification_question = None
        requirements_data = validated_config.get("application_requirements")
        if requirements_data:
            try:
                requirements = ApplicationRequirements.model_validate(requirements_data)
                clarification_question = self.clarification_service.next_question(requirements)
            except Exception:
                clarification_question = None

        return OnboardingMessageResponse(
            session_id=str(session.id),
            response=ai_resp.text,
            state=next_state,
            configuration=validated_config,
            is_complete=(next_state == "completed"),
            suggested_actions=ai_resp.suggested_actions or self.get_suggested_actions_for_state(next_state),
            proposed_runtime=validated_config if is_ready_to_provision else None,
            application_requirements=validated_config.get("application_requirements"),
            runtime_plan=validated_config.get("runtime_plan"),
            clarification_question=clarification_question,
        )

    async def _apply_requirements_intelligence(
        self,
        *,
        ai_resp: OnboardingModelResponse,
        message: str,
        current_state: str,
        current_config: dict[str, Any],
        history: list[dict[str, Any]],
    ) -> tuple[OnboardingModelResponse, ApplicationRequirements]:
        stored_requirements = current_config.get("application_requirements")
        # The connection mode is kept in the onboarding configuration while
        # the typed requirements intentionally stay provider-agnostic. Pass
        # the mode through as ownership context so extraction/planning does
        # not silently revert an already selected OAuth policy.
        if isinstance(stored_requirements, dict) and not stored_requirements.get("connection_ownership"):
            configured_mode = current_config.get("integration_mode")
            ownership = {
                "zyntry_managed": "company",
                "end_user_oauth": "end_user",
                "hybrid": "hybrid",
            }.get(configured_mode)
            if ownership:
                stored_requirements = {**stored_requirements, "connection_ownership": ownership}
        requirements = await self.requirements_extractor.extract(
            message=message,
            current_data=stored_requirements,
            history=history,
            pending_requirement=current_config.get("pending_requirement"),
        )
        ai_resp.proposed_data = {
            **ai_resp.proposed_data,
            "application_requirements": requirements.model_dump(mode="json"),
        }

        question = self.clarification_service.next_question(requirements)
        if self._should_prioritize_clarification(current_state, requirements, question):
            if question:
                ai_resp.text = (
                    "I’ve captured the requirements you provided. "
                    f"{question.question}"
                )
                ai_resp.proposed_intent = "clarify_requirements"
                ai_resp.proposed_data["pending_requirement"] = question.requirement
                ai_resp.suggested_actions = question.suggested_answers
            else:
                ready_data = self._requirements_configuration(requirements)
                ai_resp.text = (
                    "I have enough information to generate the runtime plan.\n\n"
                    "Choose the routing preference: low latency, balanced, or maximum quality."
                )
                ai_resp.proposed_intent = "requirements_ready"
                ai_resp.proposed_data = {
                    **ai_resp.proposed_data,
                    **ready_data,
                    "pending_requirement": None,
                }
                ai_resp.suggested_actions = ["Low latency", "Balanced", "Maximum quality"]
        return ai_resp, requirements

    @staticmethod
    def _should_prioritize_clarification(
        current_state: str,
        requirements: ApplicationRequirements,
        question: Any,
    ) -> bool:
        if current_state == "clarifying_requirements":
            return True
        if current_state != "onboarding_started" or question is None:
            return False
        if requirements.application_type == "general_ai_application":
            return True
        return question.requirement in {
            "document_formats",
            "external_source_types",
            "memory_scope",
        }

    @staticmethod
    def _requirements_configuration(
        requirements: ApplicationRequirements,
    ) -> dict[str, Any]:
        ownership_mode = {
            "company": "zyntry_managed",
            "end_user": "end_user_oauth",
            "hybrid": "hybrid",
        }.get(requirements.connection_ownership or "company", "zyntry_managed")
        integrations = requirements.integration_slugs()
        capabilities: dict[str, list[str]] = {}
        for requested in requirements.integrations:
            defn = integration_registry.get(requested.slug)
            if not defn:
                continue
            capabilities[defn.slug] = requested.capabilities or [
                item.slug for item in defn.capabilities
                if requested.write_access or not item.is_write
            ]
        return {
            "use_case": requirements.application_type or "general_ai_application",
            "application_type": requirements.application_type or "general_ai_application",
            "integration_mode": ownership_mode,
            "integrations": integrations,
            "capabilities": capabilities,
        }

    def _attach_runtime_plan(
        self,
        configuration: dict[str, Any],
        previous_plan: dict[str, Any] | None,
    ) -> dict[str, Any]:
        requirements_data = configuration.get("application_requirements")
        if not requirements_data:
            return configuration
        try:
            requirements = ApplicationRequirements.model_validate(requirements_data)
        except Exception:
            logger.warning("Skipping runtime plan generation for invalid requirements")
            return configuration
        plan = self.runtime_plan_generator.generate(
            requirements=requirements,
            configuration=configuration,
            previous_plan=previous_plan,
        )
        result = {**configuration, "runtime_plan": plan.model_dump(mode="json")}
        integrations = list(result.get("integrations", []))
        capabilities = dict(result.get("capabilities", {}))
        integration_modes = dict(result.get("integration_modes", {}))
        for policy in plan.integration_policies:
            slug = policy["integration_slug"]
            if slug not in integrations:
                integrations.append(slug)
            capabilities[slug] = policy.get("enabled_capabilities", [])
            integration_modes[slug] = policy.get("connection_mode", "zyntry_managed")
        result["integrations"] = integrations
        result["capabilities"] = capabilities
        result["integration_modes"] = integration_modes
        return result

    def _authorize_and_transition(
        self,
        current_state: str,
        current_config: dict[str, Any],
        proposed_intent: str | None,
        proposed_data: dict[str, Any],
    ) -> tuple[dict[str, Any], str]:
        """Backend authorization: strictly validate proposed changes and compute next state."""
        config = dict(current_config)

        if proposed_data.get("application_requirements"):
            requirements = ApplicationRequirements.model_validate(
                proposed_data["application_requirements"]
            )
            config["application_requirements"] = requirements.model_dump(mode="json")
        if "pending_requirement" in proposed_data:
            if proposed_data["pending_requirement"]:
                config["pending_requirement"] = proposed_data["pending_requirement"]
            else:
                config.pop("pending_requirement", None)

        if proposed_intent == "clarify_requirements":
            return config, "clarifying_requirements"

        if proposed_intent == "requirements_ready":
            config.update({
                key: value
                for key, value in proposed_data.items()
                if key in {
                    "use_case",
                    "application_type",
                    "integration_mode",
                    "runtime_name",
                }
                and value is not None
            })
            return self._validate_integrations_and_transition(config, proposed_data)

        if proposed_intent == "set_use_case":
            config["use_case"] = proposed_data.get("use_case", "general_ai_application")
            if proposed_data.get("runtime_name"):
                config["runtime_name"] = proposed_data["runtime_name"]
            if "integrations" in proposed_data and proposed_data["integrations"]:
                config["integrations"] = proposed_data["integrations"]
            return config, "discovering_application_type"

        if proposed_intent == "set_use_case_and_mode":
            config["use_case"] = proposed_data.get("use_case", "general_ai_application")
            config["application_type"] = proposed_data.get("application_type", "customer_facing_ai_app")
            config["integration_mode"] = proposed_data.get("integration_mode", "end_user_oauth")
            if proposed_data.get("runtime_name"):
                config["runtime_name"] = proposed_data["runtime_name"]
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
            if proposed_data.get("runtime_name"):
                config["runtime_name"] = proposed_data["runtime_name"]
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
            if proposed_data.get("runtime_name"):
                config["runtime_name"] = proposed_data["runtime_name"]
            return self._validate_integrations_and_transition(config, proposed_data)

        if proposed_intent == "confirm_configuration":
            if proposed_data.get("runtime_name"):
                config["runtime_name"] = proposed_data["runtime_name"]
            config["model"] = proposed_data.get("model", "gpt-4o")
            config["provider"] = proposed_data.get("provider", "openai")
            config["routing_strategy"] = proposed_data.get("routing_strategy", "balanced")
            config["environment"] = proposed_data.get("environment", "development")
            return config, "confirming_configuration"

        if proposed_intent == "modify_settings":
            return config, "configuring_runtime"

        # General update fallback
        for k, v in proposed_data.items():
            if k in ("use_case", "application_type", "integration_mode", "runtime_name", "model", "provider", "routing_strategy"):
                config[k] = v

        return config, current_state

    def _validate_integrations_and_transition(
        self, config: dict[str, Any], proposed_data: dict[str, Any]
    ) -> tuple[dict[str, Any], str]:
        # Merge NEW integrations with EXISTING ones (accumulate across steps)
        existing_integrations = list(config.get("integrations", []))
        existing_capabilities = dict(config.get("capabilities", {}))
        raw_integrations = proposed_data.get("integrations", [])

        for slug in raw_integrations:
            defn = integration_registry.get(slug)
            if defn:
                if defn.slug not in existing_integrations:
                    existing_integrations.append(defn.slug)
                req_caps = proposed_data.get("capabilities", {}).get(defn.slug)
                all_caps = [c.slug for c in defn.capabilities]
                if req_caps:
                    valid_caps = [c for c in req_caps if c in all_caps]
                else:
                    valid_caps = [c.slug for c in defn.capabilities if not c.is_write]
                existing_capabilities[defn.slug] = valid_caps

        config["integrations"] = existing_integrations
        config["capabilities"] = existing_capabilities
        return config, "configuring_runtime"

    def get_suggested_actions_for_state(
        self, state: str, configuration: dict[str, Any] | None = None
    ) -> list[str]:
        config = configuration or {}
        integrations = list(config.get("integrations", []))
        external = config.get("external_sources", {})
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
            actions = [
                f"Configure {self._display_name(slug)}" for slug in integrations
            ]
            actions.extend(["Add another source", "Use uploaded documents"])
            if not external.get("enabled"):
                actions.append("Add external knowledge")
            return actions
        if state == "configuring_runtime":
            return [
                f"Use {self._display_name(slug)}" for slug in integrations
            ] or ["Describe the data this runtime should use", "Add external knowledge"]
        if state == "confirming_configuration":
            return ["Confirm & Create Runtime", "Change something"]
        if state == "completed":
            return ["Generate API Key", "Go to Runtime Console"]
        return ["Continue"]

    @staticmethod
    def _display_name(slug: str) -> str:
        return slug.replace("_", " ").strip().title()

    @staticmethod
    def _resolve_connection_mode(slug: str, requested_mode: str) -> tuple[str, str]:
        """Return the effective mode and explain any safe fallback."""
        defn = integration_registry.get(slug)
        if defn is None:
            return requested_mode, "requested"
        supports_hybrid = {"zyntry_managed", "end_user_oauth"}.issubset(
            defn.supported_connection_modes
        )
        if requested_mode == "hybrid" and not supports_hybrid:
            return "zyntry_managed", "company_managed_only"
        if requested_mode not in defn.supported_connection_modes and requested_mode != "hybrid":
            raise ValueError(
                f"{defn.name} does not support the requested connection mode "
                f"'{requested_mode}'"
            )
        return requested_mode, "requested"

    async def complete_onboarding(
        self, user_id: UUID, req: OnboardingCompleteRequest
    ) -> OnboardingCompleteResponse:
        session_uuid = UUID(req.session_id)
        session = await self.uow.onboarding_sessions.get(session_uuid)
        if session is None or session.user_id != user_id:
            raise ValueError("Onboarding session not found")

        # Onboarding is non-provisioning: it stores a configuration draft.
        if session.state == "completed":
            config = session.configuration or {}
            original_config = config
            existing_policies = config.get("integration_policies", [])
            normalized_policies: list[dict[str, Any]] = []
            for policy in existing_policies:
                slug = policy.get("integration_slug")
                if not slug:
                    continue
                requested = policy.get(
                    "requested_connection_mode",
                    policy.get("connection_mode", config.get("integration_mode", "zyntry_managed")),
                )
                mode, resolution = self._resolve_connection_mode(slug, requested)
                normalized_policies.append({
                    **policy,
                    "connection_mode": mode,
                    "requested_connection_mode": requested,
                    "mode_resolution": resolution,
                })
            if normalized_policies and normalized_policies != existing_policies:
                config = {**config, "integration_policies": normalized_policies}
            config = self._attach_runtime_plan(
                config,
                previous_plan=config.get("runtime_plan"),
            )
            if config != original_config:
                await self.uow.onboarding_sessions.update(session, configuration=config)
                await self.uow.commit()
            return OnboardingCompleteResponse(
                session_id=str(session.id),
                runtime_id=None,
                runtime_name=req.runtime_name or config.get("runtime_name", "AI App Runtime"),
                environment=req.environment or config.get("environment", "development"),
                status="draft",
                enabled_integrations=normalized_policies,
                message="Configuration draft already saved. Create a project to provision the runtime.",
                application_requirements=config.get("application_requirements"),
                runtime_plan=config.get("runtime_plan"),
            )

        config = session.configuration or {}
        runtime_name = req.runtime_name or config.get("runtime_name") or f"{config.get('use_case', 'AI App').replace('_', ' ').title()} Runtime"
        env = req.environment or config.get("environment", "development")

        config = {**config, "runtime_name": runtime_name, "environment": env}

        # Record intended integrations in the draft; provision them later.
        enabled_integrations_list: list[dict[str, Any]] = []
        integrations = config.get("integrations", [])
        capabilities_map = config.get("capabilities", {})
        integration_mode = config.get("integration_mode", "zyntry_managed")
        integration_modes = {
            **config.get("integration_modes", {}),
            **req.integration_modes,
        }

        for slug in integrations:
            defn = integration_registry.get(slug)
            if defn is None:
                continue

            caps = capabilities_map.get(slug, [c.slug for c in defn.capabilities if not c.is_write])
            requested_mode = integration_modes.get(slug, integration_mode)
            mode, mode_resolution = self._resolve_connection_mode(slug, requested_mode)

            enabled_integrations_list.append({
                "integration_slug": slug,
                "connection_mode": mode,
                "requested_connection_mode": requested_mode,
                "mode_resolution": mode_resolution,
                "enabled_capabilities": caps,
                "connection_status": "not_configured",
            })

        config["integration_policies"] = enabled_integrations_list
        config = self._attach_runtime_plan(
            config,
            previous_plan=config.get("runtime_plan"),
        )

        # 3. Mark session completed (API Key generation is decoupled and user-requested)
        await self.uow.onboarding_sessions.update(
            session,
            state="completed",
            created_runtime_id=None,
            configuration=config,
            completed_at=datetime.now(UTC),
        )
        await self.uow.commit()

        integ_lines = []
        for item in enabled_integrations_list:
            slug = item["integration_slug"]
            defn = integration_registry.get(slug)
            name = defn.name if defn else slug.replace("_", " ").title()
            caps = ", ".join(c.replace("_", " ").capitalize() for c in item["enabled_capabilities"])
            integ_lines.append(f"• {name}: {caps}")

        integs_formatted = "\n".join(integ_lines) if integ_lines else "• Standard read access"

        message_markdown = (
            "Configuration draft saved.\n\n"
            f"• Name: {runtime_name}\n"
            "• Status: Draft\n"
            f"• Environment: {env.capitalize()}\n"
            f"• Routing Strategy: {config.get('routing_strategy', 'balanced').replace('_', ' ').capitalize()}\n\n"
            "Configured Integrations:\n"
            f"{integs_formatted}\n\n"
            "Next: create a project, connect the selected resources, and provision the runtime."
        )

        return OnboardingCompleteResponse(
            session_id=str(session.id),
            runtime_id=None,
            runtime_name=runtime_name,
            environment=env,
            status="draft",
            enabled_integrations=enabled_integrations_list,
            message=message_markdown,
            application_requirements=config.get("application_requirements"),
            runtime_plan=config.get("runtime_plan"),
        )
