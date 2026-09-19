from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from app.core.config import settings
from app.models.onboarding_session import OnboardingSession
from app.repositories import UnitOfWork
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
    OnboardingRequirementsError,
    RuntimePlanGenerator,
    explicitly_disables_integrations,
)
from app.services.onboarding.models import (
    OnboardingModelProvider,
    OnboardingModelResponse,
    default_onboarding_model_provider,
)
from app.services.onboarding.provider_router import build_onboarding_provider
from app.services.onboarding.telemetry import OnboardingTraceSink, use_trace
from app.services.runtimes import RuntimeCreationConflict

logger = logging.getLogger(__name__)

# These are project knowledge resources, not external connector integrations.
# They must never be reported as unsupported/coming-soon connectors when the
# model mentions uploaded documents or their file formats.
_DOCUMENT_RESOURCE_SLUGS = frozenset({
    "pdf",
    "docx",
    "txt",
    "csv",
    "markdown",
    "html",
    "json",
    "document_storage",
    "uploaded_documents",
    "uploaded_document",
})

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


class OnboardingNameMismatchError(ValueError):
    """The draft name and submitted name differ and require review."""

    code = "onboarding_name_mismatch"

    def __init__(self, saved_name: str, requested_name: str) -> None:
        self.saved_name = saved_name
        self.requested_name = requested_name
        super().__init__(
            f"The onboarding draft is named '{saved_name}', but the requested "
            f"runtime name is '{requested_name}'. Review the name before proceeding."
        )

    def as_detail(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "review_required": True,
            "saved_name": self.saved_name,
            "requested_name": self.requested_name,
        }


class OnboardingEngine:
    def __init__(
        self,
        uow: UnitOfWork,
        model_provider: OnboardingModelProvider | None = None,
    ) -> None:
        self.uow = uow
        self.model_provider = model_provider or default_onboarding_model_provider
        self.integration_service = IntegrationService(uow)
        allow_fallback = bool(getattr(settings, "ONBOARDING_ALLOW_FALLBACK", False))
        self.requirements_extractor = ModelBackedRequirementsExtractor(
            allow_fallback=allow_fallback,
        )
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
        if session and not reset and initial_prompt:
            # A new initial prompt is a new runtime draft. Older clients used
            # to send it to this endpoint without ``reset=true``; blindly
            # resuming the active session made the UI show stale requirements
            # (for example a previous customer-support/GitHub draft).
            prior_prompt = next(
                (
                    str(item.get("content", ""))
                    for item in (session.messages or [])
                    if item.get("role") == "user" and item.get("content")
                ),
                "",
            )
            def normalize(value: str) -> str:
                return re.sub(r"\s+", " ", value).strip().casefold()
            if normalize(prior_prompt) != normalize(initial_prompt):
                await self.uow.onboarding_sessions.cancel_all_active_by_user(user_id)
                await self.uow.commit()
                session = None

        if session and not reset:
            # Repair active sessions created before explicit-name extraction
            # was fixed. This keeps the review card and name input correct
            # before the user reaches the completion button.
            config = dict(session.configuration or {})
            recovered_name = self._runtime_name_from_messages(session.messages)
            configured_name = config.get("runtime_name")
            fallback_name = (
                f"{config.get('use_case', 'AI App').replace('_', ' ').title()} Runtime"
            )
            if recovered_name and (
                not configured_name
                or str(configured_name).casefold() == fallback_name.casefold()
            ):
                config["runtime_name"] = recovered_name
                session = await self.uow.onboarding_sessions.update(
                    session,
                    configuration=config,
                )
                await self.uow.commit()
            return session

        welcome_msg = {
            "role": "assistant",
            "content": (
                "Tell me what kind of AI application you are building, "
                "or what tools and data sources you want Zyntry to manage."
            ),
            "timestamp": datetime.now(UTC).isoformat(),
        }
        messages: list[dict[str, Any]] = [welcome_msg]

        trace_sink: OnboardingTraceSink | None = None
        if initial_prompt:
            messages.append({
                "role": "user",
                "content": initial_prompt,
                "timestamp": datetime.now(UTC).isoformat(),
            })
            trace_sink = OnboardingTraceSink(
                session=self.uow.session,
                user_id=user_id,
                session_id=None,
                turn_id=uuid4(),
            )
            with use_trace(trace_sink):
                ai_resp = await self.model_provider.generate_step_response(
                    user_message=initial_prompt,
                    current_state="onboarding_started",
                    current_config={},
                    history=messages,
                )
            pre_extracted_requirements: ApplicationRequirements | None = None
            requirements_error: OnboardingRequirementsError | None = None
            embedded_requirements = getattr(ai_resp, "application_requirements", None)
            if isinstance(embedded_requirements, dict):
                try:
                    pre_extracted_requirements = self.requirements_extractor.validate_embedded_requirements(
                        embedded_requirements,
                        message=initial_prompt,
                        current_data=None,
                    )
                except Exception as exc:
                    logger.warning(
                        "Embedded onboarding requirements were invalid: %s",
                        type(exc).__name__,
                    )
            if pre_extracted_requirements is None:
                try:
                    pre_extracted_requirements = await self.requirements_extractor.extract(
                        message=initial_prompt,
                        current_data=None,
                        history=self._history_for_model(messages),
                    )
                except OnboardingRequirementsError as exc:
                    requirements_error = exc
            with use_trace(trace_sink):
                ai_resp, _ = await self._apply_requirements_intelligence(
                    ai_resp=ai_resp,
                    message=initial_prompt,
                    current_state="onboarding_started",
                    current_config={},
                    history=self._history_for_model(messages),
                    pre_extracted_requirements=pre_extracted_requirements,
                    requirements_error=requirements_error,
                )
            # Preserve an explicit name from the initial prompt. The initial
            # prompt follows a different path from later messages; without
            # this merge, "Create a runtime named ..." falls back to a
            # use-case-derived name at completion time.
            extractor = getattr(self.model_provider, "_extract_runtime_name", None)
            runtime_name = extractor(initial_prompt) if callable(extractor) else None
            if runtime_name:
                ai_resp.proposed_data = {
                    **ai_resp.proposed_data,
                    "runtime_name": runtime_name,
                }
            self._apply_explicit_integration_exclusions(ai_resp, initial_prompt)
            self._filter_unavailable_integrations(ai_resp.proposed_data)
            self._append_integration_availability_notice(ai_resp)
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
        if trace_sink:
            trace_sink.bind_session_id(session.id)
        await self.uow.commit()
        return session

    @staticmethod
    def _history_for_model(messages: list[dict[str, Any]], limit: int = 12) -> list[dict[str, str]]:
        """Keep model context bounded and exclude persistence metadata."""
        bounded: list[dict[str, str]] = []
        for item in messages[-limit:]:
            role = item.get("role")
            content = item.get("content")
            if role not in {"user", "assistant"} or content is None:
                continue
            bounded.append({"role": str(role), "content": str(content)[:12000]})
        return bounded

    async def _persist_provider_error(
        self,
        session: OnboardingSession,
        messages: list[dict[str, Any]],
        current_config: dict[str, Any],
        exc: OnboardingRequirementsError,
    ) -> None:
        """Persist a safe retry marker without exposing provider diagnostics."""
        error_code = getattr(exc, "code", "onboarding_model_unavailable")
        retryable = bool(getattr(exc, "retryable", True))
        safe_message = getattr(
            exc,
            "public_message",
            "The onboarding assistant is temporarily unavailable. Please try again shortly.",
        )
        messages.append({
            "role": "assistant",
            "content": safe_message,
            "timestamp": datetime.now(UTC).isoformat(),
            "error": {"code": error_code, "retryable": retryable},
        })
        try:
            await self.uow.onboarding_sessions.update(
                session,
                messages=messages,
                configuration={
                    **current_config,
                    "onboarding_model_error": {
                        "code": error_code,
                        "retryable": retryable,
                    },
                },
            )
            await self.uow.commit()
        except Exception:
            logger.exception("Could not persist failed onboarding turn")

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
            runtime_name = (
                session.configuration.get("runtime_name")
                or session.configuration.get("use_case", "AI App").replace("_", " ").title() + " Runtime"
            )
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
        if req.idempotency_key:
            # A successful retry with the same key returns the existing turn.
            # A persisted retryable error removes only that failed turn before
            # processing again, so the conversation never accumulates copies.
            for index in range(len(messages) - 1, -1, -1):
                item = messages[index]
                if item.get("role") != "user" or item.get("idempotency_key") != req.idempotency_key:
                    continue
                following = messages[index + 1] if index + 1 < len(messages) else None
                if isinstance(following, dict) and following.get("role") == "assistant" and following.get("error"):
                    messages = messages[:index]
                elif isinstance(following, dict) and following.get("role") == "assistant":
                    return OnboardingMessageResponse(
                        session_id=str(session.id),
                        response=str(following.get("content") or ""),
                        state=session.state,
                        configuration=dict(session.configuration or {}),
                        is_complete=session.state == "completed",
                        application_requirements=(session.configuration or {}).get("application_requirements"),
                        runtime_plan=(session.configuration or {}).get("runtime_plan"),
                    )
                break
        messages.append({
            "role": "user",
            "content": req.message,
            "timestamp": datetime.now(UTC).isoformat(),
            "idempotency_key": req.idempotency_key,
        })

        current_config = dict(session.configuration or {})
        trace_sink = OnboardingTraceSink(
            session=self.uow.session,
            user_id=user_id,
            session_id=session.id,
            turn_id=uuid4(),
        )

        # Step 1: ask the conversational provider for the reply and typed
        # requirements together. A compliant production model completes this
        # turn with one provider round trip. Older/custom providers may omit
        # the typed object; only then do we call the dedicated extractor.
        model_history = self._history_for_model(messages)
        with use_trace(trace_sink):
            conversation_result = await self.model_provider.generate_step_response(
                user_message=req.message,
                current_state=session.state,
                current_config=current_config,
                history=model_history,
            )

        if isinstance(conversation_result, OnboardingRequirementsError):
            await self._persist_provider_error(session, messages, current_config, conversation_result)
            raise conversation_result
        if isinstance(conversation_result, BaseException):
            raise conversation_result

        requirements_error: OnboardingRequirementsError | None = None
        pre_extracted_requirements: ApplicationRequirements | None = None
        embedded_requirements = getattr(conversation_result, "application_requirements", None)
        if isinstance(embedded_requirements, dict):
            try:
                pre_extracted_requirements = self.requirements_extractor.validate_embedded_requirements(
                    embedded_requirements,
                    message=req.message,
                    current_data=current_config.get("application_requirements"),
                    pending_requirement=(
                        current_config.get("pending_requirement")
                        or current_config.get("onboarding_pending_question")
                    ),
                )
            except Exception as exc:
                # Do not trust an incomplete model object. The dedicated
                # extractor still validates against the same schema and is
                # used only for this compatibility/error path.
                logger.warning(
                    "Embedded onboarding requirements were invalid: %s",
                    type(exc).__name__,
                )

        if pre_extracted_requirements is None:
            try:
                pre_extracted_requirements = await self.requirements_extractor.extract(
                    message=req.message,
                    current_data=current_config.get("application_requirements"),
                    history=model_history,
                    pending_requirement=(
                        current_config.get("pending_requirement")
                        or current_config.get("onboarding_pending_question")
                    ),
                )
            except OnboardingRequirementsError as exc:
                requirements_error = exc

        with use_trace(trace_sink):
            ai_resp, _ = await self._apply_requirements_intelligence(
                ai_resp=conversation_result,
                message=req.message,
                current_state=session.state,
                current_config=current_config,
                history=model_history,
                pre_extracted_requirements=pre_extracted_requirements,
                requirements_error=requirements_error,
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
        self._apply_explicit_integration_exclusions(ai_resp, req.message)

        # Step 2: Check for direct execution / confirmation
        msg_lower = req.message.lower().strip()
        is_confirmation = self._is_explicit_runtime_confirmation(
            message=msg_lower,
            state=session.state,
            proposed_intent=ai_resp.proposed_intent,
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
        self._filter_unavailable_integrations(ai_resp.proposed_data)
        validated_config, next_state = self._authorize_and_transition(
            current_state=session.state,
            current_config=current_config,
            proposed_intent=ai_resp.proposed_intent,
            proposed_data=ai_resp.proposed_data,
        )
        validated_config.pop("onboarding_model_error", None)
        self._append_integration_availability_notice(ai_resp)
        # Keep planning behind the final conversational checkpoint. During
        # discovery and clarification we persist requirements only; a plan is
        # generated once the user confirms the completed configuration.
        if next_state in ("provisioning", "completed"):
            validated_config = self._attach_runtime_plan(
                validated_config,
                previous_plan=current_config.get("runtime_plan"),
            )
        else:
            # Use the planner's registry validation to normalize integration
            # policies, but do not persist or return the plan snapshot while
            # the conversation is still collecting requirements.
            normalized_config = self._attach_runtime_plan(
                validated_config,
                previous_plan=current_config.get("runtime_plan"),
            )
            normalized_config.pop("runtime_plan", None)
            validated_config = normalized_config

        # Append assistant response
        assistant_message: dict[str, Any] = {
            "role": "assistant",
            "content": ai_resp.text,
            "timestamp": datetime.now(UTC).isoformat(),
            "proposed_intent": ai_resp.proposed_intent,
        }
        if ai_resp.proposed_data.get("onboarding_model_error"):
            assistant_message["error"] = ai_resp.proposed_data["onboarding_model_error"]
        messages.append(assistant_message)

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
                asked_requirements = {
                    str(item)
                    for item in validated_config.get("onboarding_questions_asked", [])
                    if item
                }
                pending_requirement = validated_config.get("onboarding_pending_question")
                if pending_requirement and pending_requirement not in requirements.missing_requirements():
                    asked_requirements.add(str(pending_requirement))
                clarification_question = self.clarification_service.next_conversation_question(
                    requirements,
                    asked_requirements=asked_requirements,
                )
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

    @staticmethod
    def _is_explicit_runtime_confirmation(
        *,
        message: str,
        state: str,
        proposed_intent: str | None,
    ) -> bool:
        """Require an unambiguous create/provision instruction.

        A model intent is advisory and a bare ``yes`` may answer an integration
        or clarification question. Neither is sufficient to create a runtime.
        The user must explicitly confirm creation/provisioning.
        """

        if state not in ("confirming_configuration", "configuring_runtime"):
            return False
        normalized = re.sub(r"\s+", " ", message.strip().lower())
        explicit_phrases = (
            "confirm & create runtime",
            "confirm and create runtime",
            "confirm configuration",
            "create runtime",
            "provision runtime",
            "proceed with creation",
            "proceed with provisioning",
            "yes, create",
            "yes create",
            "looks good, create",
            "let's do it",
            "lets do it",
        )
        return any(phrase in normalized for phrase in explicit_phrases)

    async def _apply_requirements_intelligence(
        self,
        *,
        ai_resp: OnboardingModelResponse,
        message: str,
        current_state: str,
        current_config: dict[str, Any],
        history: list[dict[str, Any]],
        pre_extracted_requirements: ApplicationRequirements | None = None,
        requirements_error: OnboardingRequirementsError | None = None,
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
            }.get(configured_mode if isinstance(configured_mode, str) else "")
            if ownership:
                stored_requirements = {**stored_requirements, "connection_ownership": ownership}
        try:
            if requirements_error is not None:
                raise requirements_error
            if pre_extracted_requirements is not None:
                requirements = pre_extracted_requirements
            else:
                requirements = await self.requirements_extractor.extract(
                    message=message,
                    current_data=stored_requirements,
                    history=history,
                    pending_requirement=(
                        current_config.get("pending_requirement")
                        or current_config.get("onboarding_pending_question")
                    ),
                )
            if not requirements.connection_ownership:
                configured_mode = current_config.get("integration_mode")
                ownership = {
                    "zyntry_managed": "company",
                    "end_user_oauth": "end_user",
                    "hybrid": "hybrid",
                }.get(configured_mode if isinstance(configured_mode, str) else "")
                if ownership:
                    requirements = requirements.model_copy(update={"connection_ownership": ownership})
        except OnboardingRequirementsError as exc:
            # Never silently infer a plan when the production model is
            # unavailable. Preserve an existing validated snapshot, if any,
            # but discard the deterministic conversational provider's guesses.
            requirements = (
                ModelBackedRequirementsExtractor._validated_current(stored_requirements)
                or ApplicationRequirements()
            )
            ai_resp.proposed_data = {
                "application_requirements": requirements.model_dump(mode="json"),
                "onboarding_model_error": {
                    "code": getattr(exc, "code", "onboarding_model_unavailable"),
                    "message": getattr(
                        exc,
                        "public_message",
                        "The onboarding assistant is temporarily unavailable. Please try again shortly.",
                    ),
                    "retryable": bool(getattr(exc, "retryable", True)),
                },
            }
            ai_resp.proposed_intent = "clarify_requirements"
            ai_resp.text = (
                "I can’t safely continue because the onboarding model is unavailable. "
                "Nothing was configured. Please try again in a moment."
            )
            ai_resp.text = getattr(
                exc,
                "public_message",
                "The onboarding assistant is temporarily unavailable. Please try again shortly.",
            )
            ai_resp.suggested_actions = ["Try again"]
            return ai_resp, requirements

        requirement_configuration = self._requirements_configuration(requirements)
        # Completeness is a backend validation result. It is never supplied
        # by the model and never used as a substitute for the clarification
        # checkpoint below.
        requirements.completeness_score = requirements.calculate_completeness_score()
        ai_resp.proposed_data = {
            **ai_resp.proposed_data,
            "application_requirements": requirements.model_dump(mode="json"),
            # The model-backed requirements are authoritative for connector
            # selection. This prevents the conversational provider from
            # carrying a service mention into the draft as a direct connector.
            "integrations": requirement_configuration["integrations"],
            "capabilities": requirement_configuration["capabilities"],
            "requires_tools": requirements.requires_tools,
        }
        for key in ("use_case", "application_type", "integration_mode"):
            value = requirement_configuration.get(key)
            if value is not None:
                ai_resp.proposed_data[key] = value

        asked_requirements = {
            str(item)
            for item in current_config.get("onboarding_questions_asked", [])
            if item
        }
        pending_question = current_config.get("onboarding_pending_question")
        if pending_question and pending_question not in requirements.missing_requirements():
            asked_requirements.add(str(pending_question))
        question = self.clarification_service.next_conversation_question(
            requirements,
            asked_requirements=asked_requirements,
        )
        should_ask_context = (
            current_state == "onboarding_started"
            and not requirements.missing_requirements()
            and not current_config.get("onboarding_exploration_complete")
        )
        # The conversational model can produce a plausible but incorrect
        # connector question (for example, treating private uploaded files as
        # a ``document_storage`` integration). Once the requirements extractor
        # has validated that document formats are the next missing field, the
        # backend owns that checkpoint so the model cannot contradict the
        # resource/integration boundary. Other onboarding transitions retain
        # their existing state behavior while requirements are gathered.
        document_question = question and question.requirement == "document_formats"
        if self._should_prioritize_clarification(current_state, requirements, question) or document_question or should_ask_context:
            if question:
                ai_resp.text = (
                    "I’ve captured the requirements you provided. "
                    f"{question.question}"
                )
                ai_resp.proposed_intent = "clarify_requirements"
                ai_resp.proposed_data["pending_requirement"] = question.requirement
                ai_resp.proposed_data["onboarding_pending_question"] = question.requirement
                ai_resp.proposed_data["onboarding_questions_asked"] = sorted(asked_requirements)
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
                    "onboarding_pending_question": None,
                    "onboarding_exploration_complete": True,
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
        ownership_modes = {
            "company": "zyntry_managed",
            "end_user": "end_user_oauth",
            "hybrid": "hybrid",
        }
        ownership_mode = ownership_modes.get(requirements.connection_ownership) if requirements.connection_ownership else None
        document_resource_slugs = {
            "pdf", "docx", "txt", "csv", "markdown", "html", "json", "document_storage"
        }
        integrations = [
            slug for slug in requirements.integration_slugs()
            if slug not in document_resource_slugs
        ]
        capabilities: dict[str, list[str]] = {}
        for requested in requirements.integrations:
            if requested.slug in document_resource_slugs:
                continue
            defn = integration_registry.get(requested.slug)
            if not defn:
                continue
            capabilities[defn.slug] = requested.capabilities or [
                item.slug for item in defn.capabilities
                if requested.write_access or not item.is_write
            ]
        result: dict[str, Any] = {
            "use_case": requirements.application_type or "general_ai_application",
            "application_type": requirements.application_type or "general_ai_application",
            "integrations": integrations,
            "capabilities": capabilities,
        }
        if ownership_mode:
            result["integration_mode"] = ownership_mode
        return result

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
        document_resource_slugs = {
            "pdf", "docx", "txt", "csv", "markdown", "html", "json", "document_storage"
        }
        integrations = [
            slug for slug in result.get("integrations", [])
            if slug not in document_resource_slugs
        ]
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

    @staticmethod
    def _apply_explicit_integration_exclusions(
        ai_resp: OnboardingModelResponse,
        message: str,
    ) -> None:
        """Prevent stale/model-suggested connectors from re-entering a draft.

        A user can explicitly say that this runtime receives sanitized context
        from its host application and must not configure direct integrations.
        This guard runs after both the model and fallback extractor so a stale
        session or an over-eager model cannot add GitHub/Slack by mention alone.
        """
        lowered = message.lower()
        if not explicitly_disables_integrations(lowered):
            return
        if "onboarding_model_error" in ai_resp.proposed_data:
            return

        ai_resp.proposed_data["integrations"] = []
        ai_resp.proposed_data["capabilities"] = {}
        ai_resp.proposed_data["requires_tools"] = False
        requirements = ai_resp.proposed_data.get("application_requirements")
        if isinstance(requirements, dict):
            requirements["integrations"] = []
            requirements["requires_tools"] = False
            ai_resp.proposed_data["application_requirements"] = requirements
        if any(name in lowered for name in ("company-managed", "company managed", "internal data")):
            ai_resp.proposed_data["integration_mode"] = "zyntry_managed"
        if any(term in lowered for term in (
            "architecture investigation", "architecture analysis", "software architecture",
            "call graph", "dependency graph", "data-flow analysis", "engineering graph",
        )):
            ai_resp.proposed_data["use_case"] = "architecture_analysis"
            ai_resp.proposed_data["application_type"] = "architecture_analysis"
        runtime_name = ai_resp.proposed_data.get("runtime_name")
        label = f" for '{runtime_name}'" if runtime_name else ""
        use_case = str(ai_resp.proposed_data.get("use_case") or "general_ai_application")
        title = {
            "architecture_analysis": "architecture-analysis",
            "ai_customer_support": "customer-support",
            "developer_ai_assistant": "developer-assistant",
            "knowledge_search_rag": "knowledge-search",
        }.get(use_case, use_case.replace("_", "-"))
        ai_resp.text = (
            f"I’ll configure a {title} runtime{label} without direct integrations. "
            "Your application will provide a limited, sanitized context slice and evidence references. "
            "You can add approved integrations later if the workflow needs them."
        )
        ai_resp.suggested_actions = ["Continue without integrations", "Add an integration later"]

    @staticmethod
    def _filter_unavailable_integrations(proposed_data: dict[str, Any]) -> None:
        """Keep beta/coming-soon/unknown connectors out of a runtime draft.

        This is intentionally a user-facing clarification rather than a hard
        request failure. The requested names are retained in metadata so the
        response can explain what happened and the user can choose another
        source.
        """
        raw_integrations = proposed_data.get("integrations")
        if not isinstance(raw_integrations, list):
            return

        available: list[str] = []
        requires_documents = bool(proposed_data.get("requires_documents"))

        def is_document_resource(value: str) -> bool:
            normalized = value.strip().lower().replace(" ", "_")
            definition = integration_registry.get(normalized)
            canonical = definition.slug if definition else normalized
            return canonical in _DOCUMENT_RESOURCE_SLUGS

        unsupported = [
            item for item in proposed_data.get("unsupported_integrations", [])
            if isinstance(item, str) and item.strip() and not is_document_resource(item)
        ]
        coming_soon = [
            item for item in proposed_data.get("coming_soon_integrations", [])
            if isinstance(item, str) and item.strip() and not is_document_resource(item)
        ]
        for item in raw_integrations:
            slug = item.get("slug") if isinstance(item, dict) else item
            if not isinstance(slug, str):
                continue
            slug = slug.strip().lower()
            if is_document_resource(slug):
                requires_documents = True
                continue
            definition = integration_registry.get(slug)
            if definition is None:
                if slug and slug not in unsupported:
                    unsupported.append(slug)
                continue
            if (
                not definition.enabled
                or definition.status in {"disabled", "deprecated", "coming_soon"}
            ):
                if definition.name not in coming_soon:
                    coming_soon.append(definition.name)
                continue
            if definition.slug not in available:
                available.append(definition.slug)

        proposed_data["integrations"] = available
        if requires_documents:
            proposed_data["requires_documents"] = True
            requirements = proposed_data.get("application_requirements")
            if isinstance(requirements, dict):
                requirements["requires_documents"] = True
        if unsupported:
            proposed_data["unsupported_integrations"] = unsupported
        else:
            proposed_data.pop("unsupported_integrations", None)
        if coming_soon:
            proposed_data["coming_soon_integrations"] = coming_soon
        else:
            proposed_data.pop("coming_soon_integrations", None)

    @staticmethod
    def _append_integration_availability_notice(ai_resp: OnboardingModelResponse) -> None:
        proposed_data = ai_resp.proposed_data

        def is_document_resource(value: str) -> bool:
            normalized = value.strip().lower().replace(" ", "_")
            definition = integration_registry.get(normalized)
            canonical = definition.slug if definition else normalized
            return canonical in _DOCUMENT_RESOURCE_SLUGS

        unsupported_names = [
            item for item in proposed_data.get("unsupported_integrations", [])
            if isinstance(item, str) and item.strip() and not is_document_resource(item)
        ]
        coming_soon_names = [
            item for item in proposed_data.get("coming_soon_integrations", [])
            if isinstance(item, str) and item.strip() and not is_document_resource(item)
        ]
        # Keep the response state clean even when a conversational model leaves
        # stale document-resource labels in its proposed metadata.
        proposed_data["requires_documents"] = bool(
            proposed_data.get("requires_documents")
            or any(is_document_resource(item) for item in proposed_data.get("unsupported_integrations", []) if isinstance(item, str))
            or any(is_document_resource(item) for item in proposed_data.get("coming_soon_integrations", []) if isinstance(item, str))
        )
        if proposed_data["requires_documents"]:
            requirements = proposed_data.get("application_requirements")
            if isinstance(requirements, dict):
                requirements["requires_documents"] = True
        if unsupported_names:
            proposed_data["unsupported_integrations"] = unsupported_names
        else:
            proposed_data.pop("unsupported_integrations", None)
        if coming_soon_names:
            proposed_data["coming_soon_integrations"] = coming_soon_names
        else:
            proposed_data.pop("coming_soon_integrations", None)
        notices: list[str] = []
        if unsupported_names:
            notices.append(
                f"{', '.join(unsupported_names)} is not supported by Zyntry yet."
            )
        if coming_soon_names:
            notices.append(
                f"{', '.join(coming_soon_names)} is coming soon and is not available for this runtime yet."
            )
        if not notices:
            return
        ai_resp.text = (
            "\n\n".join(notices)
            + "\n\nI left those sources out of the runtime draft. "
            "Would you like to continue with supported integrations, or describe another source?\n\n"
            + ai_resp.text.strip()
        )
        ai_resp.suggested_actions = list(dict.fromkeys([
            "Show supported integrations",
            "Continue without those sources",
            *ai_resp.suggested_actions,
        ]))[:8]

    def _runtime_name_from_messages(self, messages: list[dict[str, Any]] | None) -> str | None:
        """Recover a name from an earlier user turn in an existing session.

        Sessions created before the name-extraction fix may already contain a
        use-case-derived name in their configuration. Inspecting the stored
        user messages lets completion repair that draft without requiring the
        user to start over.
        """
        extractor = getattr(self.model_provider, "_extract_runtime_name", None)
        if not callable(extractor):
            return None
        for item in reversed(messages or []):
            if item.get("role") != "user":
                continue
            content = item.get("content")
            if not isinstance(content, str):
                continue
            name = extractor(content)
            if name:
                return name
        return None

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
        # Empty integrations normally mean that a step did not change the
        # selection. When the extractor also marks tools as disabled, it is an
        # explicit request to clear connectors from a legacy draft.
        if (
            proposed_data.get("integrations") == []
            and proposed_data.get("requires_tools") is False
        ):
            config["integrations"] = []
            config["capabilities"] = {}
        # A name is independent of the onboarding intent. In particular, the
        # first long prompt often asks a clarification question, and that
        # branch must not discard an explicit name while requirements are being
        # collected.
        if proposed_data.get("runtime_name"):
            config["runtime_name"] = str(proposed_data["runtime_name"]).strip()[:255]
        if "pending_requirement" in proposed_data:
            if proposed_data["pending_requirement"]:
                config["pending_requirement"] = proposed_data["pending_requirement"]
            else:
                config.pop("pending_requirement", None)
        if "onboarding_pending_question" in proposed_data:
            pending = proposed_data["onboarding_pending_question"]
            if pending:
                config["onboarding_pending_question"] = str(pending)
            else:
                config.pop("onboarding_pending_question", None)
        if "onboarding_questions_asked" in proposed_data:
            config["onboarding_questions_asked"] = list(dict.fromkeys(
                str(item) for item in proposed_data["onboarding_questions_asked"] if item
            ))
        if "onboarding_exploration_complete" in proposed_data:
            config["onboarding_exploration_complete"] = bool(
                proposed_data["onboarding_exploration_complete"]
            )

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
            if proposed_data.get("integration_mode"):
                config["integration_mode"] = proposed_data["integration_mode"]
            if proposed_data.get("runtime_name"):
                config["runtime_name"] = proposed_data["runtime_name"]
            if "integrations" in proposed_data and proposed_data["integrations"]:
                config["integrations"] = proposed_data["integrations"]
            if "capabilities" in proposed_data and proposed_data["capabilities"]:
                config["capabilities"] = proposed_data["capabilities"]
            return config, "selecting_integrations"

        if proposed_intent == "set_application_type":
            config["application_type"] = proposed_data.get("application_type", "customer_facing_ai_app")
            mode = proposed_data.get("integration_mode")
            if mode in ("zyntry_managed", "end_user_oauth", "hybrid"):
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
            config["model"] = proposed_data.get("model", "automatic")
            config["provider"] = proposed_data.get("provider", "automatic")
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
    def _resolve_connection_mode(slug: str, requested_mode: str | None) -> tuple[str | None, str]:
        """Return the effective mode and explain any safe fallback."""
        if not requested_mode:
            return None, "not_selected"
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

        # Completion is idempotent.  A completed onboarding session owns one
        # real, preconfigured Runtime record; the project binding/build gate
        # still happens later when the user chooses a project.
        if session.state == "completed":
            config = session.configuration or {}
            recovered_name = self._runtime_name_from_messages(session.messages)
            configured_name = config.get("runtime_name")
            requested_name = (req.runtime_name or "").strip()
            saved_name = str(recovered_name or configured_name or "").strip()
            if (
                requested_name
                and saved_name
                and requested_name.casefold() != saved_name.casefold()
                and not req.name_reviewed
            ):
                raise OnboardingNameMismatchError(saved_name, requested_name)
            fallback_name = (
                f"{config.get('use_case', 'AI App').replace('_', ' ').title()} Runtime"
            )
            if recovered_name and (
                not requested_name
                or requested_name.casefold()
                in {str(configured_name or '').casefold(), fallback_name.casefold()}
            ):
                config = {**config, "runtime_name": recovered_name}
            elif requested_name and req.name_reviewed:
                # The user explicitly reviewed and chose a different name;
                # persist that choice so a later retry does not reopen the
                # same mismatch dialog.
                config = {**config, "runtime_name": requested_name}
            existing_policies = config.get("integration_policies", [])
            document_resource_slugs = {
                "pdf", "docx", "txt", "csv", "markdown", "html", "json", "document_storage"
            }
            normalized_policies: list[dict[str, Any]] = []
            for policy in existing_policies:
                slug = policy.get("integration_slug")
                if not slug or slug in document_resource_slugs:
                    continue
                requested = policy.get(
                    "requested_connection_mode",
                    policy.get("connection_mode", config.get("integration_mode")),
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
            runtime, config = await self._ensure_onboarding_runtime(
                user_id=user_id,
                session=session,
                config=config,
                enabled_integrations=normalized_policies,
                runtime_name=(
                    recovered_name
                    if recovered_name and (
                        not requested_name
                        or requested_name.casefold()
                        in {str(configured_name or '').casefold(), fallback_name.casefold()}
                    )
                    else requested_name or config.get("runtime_name", "AI App Runtime")
                ),
                environment=req.environment or config.get("environment", "development"),
            )
            return OnboardingCompleteResponse(
                session_id=str(session.id),
                runtime_id=str(runtime.id),
                runtime_name=runtime.name,
                environment=runtime.environment,
                status=runtime.status,
                enabled_integrations=normalized_policies,
                message=(
                    "Runtime created and ready to attach to a project. "
                    "Connect its resources and build it from the Runtime Console."
                ),
                application_requirements=config.get("application_requirements"),
                runtime_plan=config.get("runtime_plan"),
            )

        config = session.configuration or {}
        recovered_name = self._runtime_name_from_messages(session.messages)
        configured_name = config.get("runtime_name")
        fallback_name = f"{config.get('use_case', 'AI App').replace('_', ' ').title()} Runtime"
        requested_name = (req.runtime_name or "").strip()
        saved_name = str(recovered_name or configured_name or "").strip()
        if (
            requested_name
            and saved_name
            and requested_name.casefold() != saved_name.casefold()
            and not req.name_reviewed
        ):
            raise OnboardingNameMismatchError(saved_name, requested_name)
        if recovered_name and (
            not requested_name
            or requested_name.casefold()
            in {str(configured_name or '').casefold(), fallback_name.casefold()}
        ):
            runtime_name = recovered_name
        else:
            runtime_name = requested_name or configured_name or fallback_name
        env = req.environment or config.get("environment", "development")

        config = {**config, "runtime_name": runtime_name, "environment": env}

        # Record intended integrations before creating the preconfigured
        # runtime.  Connection rows are materialized now, but remain
        # connection_required until the project/provider is configured.
        enabled_integrations_list: list[dict[str, Any]] = []
        document_resource_slugs = {
            "pdf", "docx", "txt", "csv", "markdown", "html", "json", "document_storage"
        }
        integrations = [
            slug for slug in config.get("integrations", [])
            if slug not in document_resource_slugs
        ]
        capabilities_map = config.get("capabilities", {})
        integration_mode = config.get("integration_mode")
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
            if not requested_mode:
                raise ValueError(
                    f"Choose who owns the {defn.name} connection before creating the runtime."
                )
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

        runtime, config = await self._ensure_onboarding_runtime(
            user_id=user_id,
            session=session,
            config=config,
            enabled_integrations=enabled_integrations_list,
            runtime_name=runtime_name,
            environment=env,
        )

        integ_lines = []
        for item in enabled_integrations_list:
            slug = item["integration_slug"]
            defn = integration_registry.get(slug)
            name = defn.name if defn else slug.replace("_", " ").title()
            caps = ", ".join(c.replace("_", " ").capitalize() for c in item["enabled_capabilities"])
            integ_lines.append(f"• {name}: {caps}")

        integs_formatted = "\n".join(integ_lines) if integ_lines else "• Standard read access"

        message_markdown = (
            "Runtime created.\n\n"
            f"• Name: {runtime_name}\n"
            f"• Status: {runtime.status.replace('_', ' ').title()}\n"
            f"• Environment: {env.capitalize()}\n"
            f"• Routing Strategy: {config.get('routing_strategy', 'balanced').replace('_', ' ').capitalize()}\n\n"
            "Configured Integrations:\n"
            f"{integs_formatted}\n\n"
            "Next: attach it to a project, connect the selected resources, and build it."
        )

        return OnboardingCompleteResponse(
            session_id=str(session.id),
            runtime_id=str(runtime.id),
            runtime_name=runtime_name,
            environment=env,
            status=runtime.status,
            enabled_integrations=enabled_integrations_list,
            message=message_markdown,
            application_requirements=config.get("application_requirements"),
            runtime_plan=config.get("runtime_plan"),
        )

    async def _ensure_onboarding_runtime(
        self,
        *,
        user_id: UUID,
        session: OnboardingSession,
        config: dict[str, Any],
        enabled_integrations: list[dict[str, Any]],
        runtime_name: str,
        environment: str,
    ) -> tuple[Any, dict[str, Any]]:
        """Create or reuse the real preconfigured runtime for a session.

        Onboarding is allowed to create the runtime definition without a
        project.  The runtime remains ``preconfigured`` until a project,
        credentials, documents, and connections are supplied.  The session
        marker makes retries safe and prevents duplicate runtimes.
        """
        session_id = str(session.id)
        runtime = None

        if session.created_runtime_id:
            runtime = await self.uow.runtimes.get(session.created_runtime_id)

        stored_runtime_id = config.get("runtime_id")
        if runtime is None and stored_runtime_id:
            try:
                runtime = await self.uow.runtimes.get(UUID(str(stored_runtime_id)))
            except (TypeError, ValueError):
                runtime = None

        existing_by_name = await self.uow.runtimes.get_by_owner_and_name(user_id, runtime_name)
        if runtime is None and existing_by_name is not None:
            existing_marker = str((existing_by_name.config or {}).get("onboarding_session_id") or "")
            if existing_marker == session_id:
                runtime = existing_by_name
            else:
                raise RuntimeCreationConflict(
                    "runtime_name_already_exists",
                    (
                        f"A runtime named '{existing_by_name.name}' already exists. "
                        "Review the existing runtime before proceeding."
                    ),
                    existing_by_name,
                )

        if runtime is None:
            provider, model, fallback_models = self._runtime_model_selection(config)
            application_requirements = config.get("application_requirements")
            if not isinstance(application_requirements, dict):
                application_requirements = {}
            requires_documents = bool(
                config.get("requires_documents")
                or application_requirements.get("requires_documents")
            )
            runtime_config = {
                "onboarding_session_id": session_id,
                "onboarding_requirements": config.get("application_requirements"),
                "runtime_plan": config.get("runtime_plan"),
                "integrations": config.get("integrations", []),
                "capabilities": config.get("capabilities", {}),
                "integration_mode": config.get("integration_mode"),
                "integration_modes": config.get("integration_modes", {}),
                "requires_documents": requires_documents,
                "document_formats": application_requirements.get("document_formats", []),
                "external_sources": config.get("external_sources", {}),
                "memory_policy": config.get("memory_policy"),
                "provider_preference": config.get("provider") or "automatic",
                "model_preference": config.get("model") or "automatic",
            }
            runtime = await self.uow.runtimes.create(
                user_id=user_id,
                project_id=None,
                organization_id=None,
                name=runtime_name,
                environment=environment or "development",
                provider=provider,
                model=model,
                fallback_models=fallback_models,
                routing_strategy=config.get("routing_strategy") or "balanced",
                embedding_model=config.get("embedding_model") or "text-embedding-3-small",
                vector_store=config.get("vector_store") or "pgvector",
                chunk_size=int(config.get("chunk_size") or 512),
                chunk_overlap=int(config.get("chunk_overlap") or 64),
                system_instructions=config.get("system_instructions"),
                security_policies=config.get("security_policies") or {},
                config=runtime_config,
                status="preconfigured",
                health=0.0,
            )

        # Keep the integrations API and the runtime config in sync from the
        # moment the runtime is created, rather than waiting for project bind.
        if enabled_integrations:
            await self.integration_service.reconcile_runtime_policies(
                runtime.id,
                enabled_integrations,
            )

        config = {
            **config,
            "runtime_id": str(runtime.id),
            "runtime_name": runtime.name,
            "runtime_status": runtime.status,
            "onboarding_session_id": session_id,
        }
        await self.uow.onboarding_sessions.update(
            session,
            state="completed",
            created_runtime_id=runtime.id,
            configuration=config,
            completed_at=session.completed_at or datetime.now(UTC),
        )
        await self.uow.commit()
        return runtime, config

    @staticmethod
    def _runtime_model_selection(config: dict[str, Any]) -> tuple[str, str, list[str]]:
        """Resolve onboarding's automatic preference to a valid runtime pair."""
        configured_provider = str(config.get("provider") or "automatic").strip().lower()
        configured_model = str(config.get("model") or "automatic").strip()
        automatic_values = {"", "auto", "automatic", "dynamic", "routing"}

        if configured_provider not in automatic_values and configured_model.lower() not in automatic_values:
            return configured_provider, configured_model, list(config.get("fallback_models") or [])

        routed, _ = build_onboarding_provider()
        candidates = list(getattr(routed, "candidates", []) or [])
        selected = None
        if configured_provider not in automatic_values:
            selected = next(
                (candidate for candidate in candidates if candidate.provider == configured_provider),
                None,
            )
        if selected is None and candidates:
            selected = candidates[0]
        if selected is not None:
            fallback_models = [
                candidate.model
                for candidate in candidates
                if candidate.provider != selected.provider or candidate.model != selected.model
            ]
            return selected.provider, selected.model, list(dict.fromkeys(fallback_models))

        # Runtime creation does not require provider credentials.  Build-time
        # validation will surface any missing credential in the console.
        return "openai", "gpt-4o-mini", []
