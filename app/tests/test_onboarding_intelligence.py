from __future__ import annotations

import httpx
import pytest

from app.schemas.onboarding_intelligence import ApplicationRequirements
from app.services.onboarding import provider_router
from app.services.onboarding.engine import OnboardingEngine
from app.services.onboarding.intelligence import (
    AdaptiveClarificationService,
    ModelBackedRequirementsExtractor,
    OnboardingModelRateLimitedError,
    RuntimePlanGenerator,
)
from app.services.onboarding.models import (
    ConfiguredOnboardingModelProvider,
    OnboardingModelResponse,
)
from app.services.onboarding.provider_router import (
    OnboardingProviderCandidate,
    RoutedOnboardingLLMProvider,
)
from app.services.onboarding.structured_schema import onboarding_response_schema
from app.services.rag import OpenAILLMProvider


class FakeLLM:
    async def generate(self, messages, model, max_tokens=2048, temperature=0.7):
        return (
            '{"schema_version":"1.0","application_type":"resume_analyzer",'
            '"primary_function":"Score resumes","target_users":["graduates"],'
            '"inputs":["resume"],"outputs":["ATS score"],"requires_documents":true,'
            '"document_formats":["pdf","docx"],"requires_external_data":false,'
            '"requires_tools":false,"requires_memory":false,"confidence":0.94}',
            42,
        )


class NaturalLanguageThenJsonLLM:
    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, messages, model, max_tokens=2048, temperature=0.7):
        self.calls += 1
        if self.calls == 1:
            return ("I captured the requirements and will continue.", 12)
        return (
            '{"schema_version":"1.0","application_type":"ai_customer_support",'
            '"primary_function":"Answer customer questions",'
            '"target_users":["customers","support teams"],'
            '"inputs":["customer questions"],"outputs":["support answers"],'
            '"requires_documents":true,"document_formats":["pdf"],'
            '"requires_external_data":false,"requires_tools":true,'
            '"requires_memory":true,"memory_scope":"session",'
            '"connection_ownership":"company","integrations":["postgresql"],'
            '"integration_decisions":["postgresql"],"confidence":0.9}',
            42,
        )


@pytest.mark.asyncio
async def test_model_extraction_is_validated_and_merged() -> None:
    extractor = ModelBackedRequirementsExtractor(provider=FakeLLM())
    requirements = await extractor.extract(
        "I am building a resume analyzer for graduates",
        current_data={"application_type": "resume_analyzer"},
    )

    assert requirements.application_type == "resume_analyzer"
    assert requirements.document_formats == ["pdf", "docx"]
    assert requirements.confidence == 0.94
    assert requirements.extraction_source == "model"


@pytest.mark.asyncio
async def test_model_extraction_repairs_non_json_provider_response() -> None:
    provider = NaturalLanguageThenJsonLLM()
    extractor = ModelBackedRequirementsExtractor(provider=provider)

    requirements = await extractor.extract(
        "Use company-managed PostgreSQL and private project documents.",
        current_data={"application_type": "ai_customer_support"},
    )

    assert provider.calls == 2
    assert requirements.integration_slugs() == ["postgresql"]
    assert requirements.requires_documents is True
    assert requirements.extraction_source == "model"


class RateLimitedLLM:
    async def generate(self, messages, model, max_tokens=2048, temperature=0.7):
        request = httpx.Request("POST", "https://example.test/generate")
        response = httpx.Response(429, request=request)
        raise httpx.HTTPStatusError("provider quota exceeded", request=request, response=response)


@pytest.mark.asyncio
async def test_model_extraction_maps_provider_429_to_safe_retryable_error() -> None:
    extractor = ModelBackedRequirementsExtractor(provider=RateLimitedLLM())

    with pytest.raises(OnboardingModelRateLimitedError) as raised:
        await extractor.extract("Build a customer support assistant")

    assert raised.value.code == "onboarding_provider_rate_limited"
    assert raised.value.retryable is True
    assert raised.value.public_message == (
        "The onboarding assistant is temporarily busy. Please try again shortly."
    )


@pytest.mark.asyncio
async def test_conversational_provider_maps_provider_429_to_safe_retryable_error(monkeypatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "ONBOARDING_ALLOW_FALLBACK", False)
    monkeypatch.setattr(
        ConfiguredOnboardingModelProvider,
        "_provider",
        staticmethod(lambda: (RateLimitedLLM(), "gemini-2.5-flash")),
    )
    provider = ConfiguredOnboardingModelProvider()

    with pytest.raises(OnboardingModelRateLimitedError) as raised:
        await provider.generate_step_response(
            user_message="Build a customer support assistant",
            current_state="onboarding_started",
            current_config={},
            history=[],
        )

    assert raised.value.public_message == (
        "The onboarding assistant is temporarily busy. Please try again shortly."
    )


@pytest.mark.asyncio
async def test_conversational_provider_accepts_embedded_requirements(monkeypatch) -> None:
    class StructuredLLM:
        async def generate(self, messages, model, max_tokens=2048, temperature=0.7):
            return (
                '{"text":"I understand the application.",'
                '"proposed_intent":"clarify_requirements",'
                '"proposed_data":{},"suggested_actions":[],"application_requirements":{'
                '"schema_version":"1.0","application_type":"ai_customer_support",'
                '"primary_function":"Answer customer questions",'
                '"target_users":["customers"],"inputs":["questions"],'
                '"outputs":["support answers"],"requires_documents":true,'
                '"document_formats":["pdf"],"requires_external_data":false,'
                '"requires_tools":false,"requires_memory":true,"memory_scope":"session",'
                '"confidence":0.9}}',
                24,
            )

    provider = ConfiguredOnboardingModelProvider()
    monkeypatch.setattr(
        ConfiguredOnboardingModelProvider,
        "_provider",
        staticmethod(lambda: (StructuredLLM(), "gemini-2.5-flash")),
    )

    response = await provider.generate_step_response(
        user_message="Build a customer support assistant",
        current_state="onboarding_started",
        current_config={},
        history=[],
    )

    assert response.application_requirements is not None
    assert response.application_requirements["application_type"] == "ai_customer_support"


@pytest.mark.asyncio
async def test_conversational_provider_requests_native_response_schema(monkeypatch) -> None:
    class SchemaAwareLLM:
        def __init__(self) -> None:
            self.response_schema = None

        async def generate(
            self,
            messages,
            model,
            max_tokens=2048,
            temperature=0.7,
            response_schema=None,
        ):
            self.response_schema = response_schema
            return (
                '{"text":"I understand.","proposed_intent":"clarify_requirements",'
                '"proposed_data":{},"suggested_actions":[],"application_requirements":{'
                '"schema_version":"1.0","application_type":"ai_customer_support",'
                '"primary_function":"Answer customer questions","target_users":["customers"],'
                '"inputs":["questions"],"outputs":["answers"],"requires_ai":true,'
                '"requires_documents":false,"document_formats":[],"requires_external_data":false,'
                '"external_source_types":[],"requires_tools":false,"requires_memory":false,'
                '"memory_scope":null,"connection_ownership":null,"integrations":[],'
                '"integration_decisions":[],"requested_actions":[],"constraints":[],"'
                'data_sensitivity":null,"expected_scale":null,"assumptions":[],"confidence":0.9}}',
                12,
            )

    llm = SchemaAwareLLM()
    provider = ConfiguredOnboardingModelProvider()
    monkeypatch.setattr(
        ConfiguredOnboardingModelProvider,
        "_provider",
        staticmethod(lambda: (llm, "gemini-2.5-flash")),
    )

    response = await provider.generate_step_response(
        user_message="Build a customer support assistant",
        current_state="onboarding_started",
        current_config={},
        history=[],
    )

    assert response.application_requirements is not None
    assert llm.response_schema == onboarding_response_schema()
    assert llm.response_schema["properties"]["application_requirements"]["type"] == "OBJECT"


@pytest.mark.asyncio
async def test_conversational_provider_repairs_one_malformed_response(monkeypatch) -> None:
    class RepairLLM:
        def __init__(self) -> None:
            self.calls = 0
            self.schemas = []

        async def generate(
            self,
            messages,
            model,
            max_tokens=2048,
            temperature=0.7,
            response_schema=None,
        ):
            self.calls += 1
            self.schemas.append(response_schema)
            if self.calls == 1:
                return ("not-json", 5)
            return (
                '{"text":"Repaired.","proposed_intent":"clarify_requirements",'
                '"proposed_data":{},"suggested_actions":[],"application_requirements":{}}',
                7,
            )

    llm = RepairLLM()
    provider = ConfiguredOnboardingModelProvider()
    monkeypatch.setattr(
        ConfiguredOnboardingModelProvider,
        "_provider",
        staticmethod(lambda: (llm, "gemini-2.5-flash")),
    )

    response = await provider.generate_step_response(
        user_message="Build a support assistant",
        current_state="onboarding_started",
        current_config={},
        history=[],
    )

    assert response.text == "Repaired."
    assert llm.calls == 2
    assert llm.schemas == [onboarding_response_schema(), onboarding_response_schema()]


def test_model_payload_normalizes_string_integration_decisions() -> None:
    payload = {
        "application_type": "customer_support",
        "primary_function": "Answer support questions",
        "integrations": [
            {"slug": "document_storage", "purpose": "Private documents"},
            {"slug": "postgresql", "purpose": "Customer records"},
        ],
        "integration_decisions": ["document_storage", "postgresql"],
    }

    normalized = ModelBackedRequirementsExtractor._prepare_model_payload(payload)
    requirements = ApplicationRequirements.model_validate(normalized)

    assert [item.slug for item in requirements.integration_decisions] == [
        "document_storage",
        "postgresql",
    ]
    assert all(item.decision == "direct" for item in requirements.integration_decisions)


def test_model_json_parser_repairs_missing_commas_without_changing_values() -> None:
    parsed = ModelBackedRequirementsExtractor._parse_json(
        """```json
        {
          "application_type": "ai_customer_support"
          "primary_function": "Answer customer questions",
          "integrations": [
            {"slug": "postgresql"}
            {"slug": "slack"}
          ],
        }
        ```"""
    )

    assert parsed["application_type"] == "ai_customer_support"
    assert parsed["primary_function"] == "Answer customer questions"
    assert parsed["integrations"] == [{"slug": "postgresql"}, {"slug": "slack"}]


def test_conversational_parser_repairs_safe_json_syntax_before_validation() -> None:
    content = """{
      "text": "Captured.",
      "proposed_intent": "clarify_requirements",
      "proposed_data": {},
      "suggested_actions": [],
      "application_requirements": {
        "application_type": "customer_support",
        "primary_function": "Answer customer questions",
        "target_users": ["customers"],
        "inputs": ["question"],
        "outputs": ["answer"],
        "requires_documents": true,
        "document_formats": ["pdf"],
        "requires_external_data": false,
        "requires_tools": false,
        "requires_memory": true,
        "memory_scope": "session"
      }
    }""".replace('"text": "Captured.",', '"text": "Captured."')

    response = ConfiguredOnboardingModelProvider._parse_response(content)

    assert response.text == "Captured."
    assert response.application_requirements["application_type"] == "customer_support"


def test_conversational_parser_normalizes_compatible_requirements() -> None:
    response = ConfiguredOnboardingModelProvider._parse_response(
        '{"text":"I need one more detail.",'
        '"proposed_intent":"clarify_requirements",'
        '"proposed_data":{},"suggested_actions":[],'
        '"application_requirements":{"integration_decisions":["postgresql"]}}'
    )

    assert response.application_requirements is not None
    assert response.application_requirements["schema_version"] == "1.0"
    assert response.application_requirements["integration_decisions"] == [
        {
            "slug": "postgresql",
            "decision": "direct",
            "reason": "The model selected this as a direct runtime integration.",
        }
    ]


def test_conversational_parser_keeps_incomplete_json_as_clarification() -> None:
    response = ConfiguredOnboardingModelProvider._parse_response(
        '{"text":"Tell me more about the users."}'
    )

    assert response.proposed_intent == "clarify_requirements"
    assert response.proposed_data == {}
    assert response.suggested_actions == []
    assert response.application_requirements["schema_version"] == "1.0"


def test_conversational_parser_discards_invalid_nested_requirements_safely() -> None:
    response = ConfiguredOnboardingModelProvider._parse_response(
        '{"text":"I need one more detail.",'
        '"proposed_intent":"clarify_requirements",'
        '"proposed_data":{},"suggested_actions":[],'
        '"application_requirements":{"requires_ai":null,'
        '"memory_scope":"not-a-supported-scope"}}'
    )

    assert response.application_requirements is not None
    assert response.application_requirements["requires_ai"] is True
    assert response.application_requirements["memory_scope"] is None


def test_embedded_requirements_apply_explicit_application_type_answer() -> None:
    extractor = ModelBackedRequirementsExtractor(provider=None)
    requirements = extractor.validate_embedded_requirements(
        {},
        message="Customer support",
        pending_requirement="application_type",
    )

    assert requirements.application_type == "ai_customer_support"


def test_embedded_requirements_apply_explicit_target_users_answer() -> None:
    extractor = ModelBackedRequirementsExtractor(provider=None)
    requirements = extractor.validate_embedded_requirements(
        {},
        message="Customers and support agents",
        pending_requirement="target_users",
    )

    assert requirements.target_users == ["customers", "support agents"]


def test_document_storage_is_a_resource_not_an_unsupported_connector() -> None:
    proposed_data = {
        "integrations": ["document_storage"],
        "unsupported_integrations": ["document_storage"],
        "coming_soon_integrations": ["Uploaded Documents"],
    }

    OnboardingEngine._filter_unavailable_integrations(proposed_data)

    assert proposed_data["integrations"] == []
    assert proposed_data["requires_documents"] is True
    assert "unsupported_integrations" not in proposed_data
    assert "coming_soon_integrations" not in proposed_data

    response = OnboardingModelResponse(
        text="I captured the document requirements.",
        proposed_intent="clarify_requirements",
        proposed_data={
            "unsupported_integrations": ["document_storage"],
            "coming_soon_integrations": ["Uploaded Documents"],
        },
        suggested_actions=[],
    )
    OnboardingEngine._append_integration_availability_notice(response)

    assert response.text == "I captured the document requirements."
    assert response.proposed_data["requires_documents"] is True


def test_model_payload_normalizes_follow_up_requirements() -> None:
    payload = {
        "application_type": "ai_customer_support",
        "primary_function": "Answer customer and support-team questions",
        "target_users": "customers and support teams",
        "inputs": "private documents and PostgreSQL records",
        "outputs": "support answers",
        "requires_documents": True,
        "document_formats": "PDF, DOCX, TXT, Markdown, CSV, and JSON",
        "requires_external_data": False,
        "requires_tools": True,
        "requires_memory": True,
        "memory_scope": "session",
        "connection_ownership": "company-managed",
        "integrations": ["postgresql"],
        "integration_decisions": ["postgresql"],
        "data_sensitivity": "confidential",
        "confidence": 0.9,
    }

    normalized = ModelBackedRequirementsExtractor._prepare_model_payload(payload)
    requirements = ApplicationRequirements.model_validate(normalized)

    assert requirements.connection_ownership == "company"
    assert requirements.integration_slugs() == ["postgresql"]
    assert requirements.document_formats == ["PDF", "DOCX", "TXT", "Markdown", "CSV", "JSON"]


@pytest.mark.asyncio
async def test_onboarding_provider_router_fails_over_to_configured_provider(monkeypatch) -> None:
    from app.services.onboarding import provider_router
    from app.services.provider_health import ProviderHealth

    class BusyAdapter:
        async def generate(self, **kwargs):
            request = httpx.Request("POST", "https://example.test/generate")
            response = httpx.Response(429, request=request)
            raise httpx.HTTPStatusError("busy", request=request, response=response)

    class WorkingAdapter:
        async def generate(self, **kwargs):
            return '{"ok": true}', 4

    adapters = {"google": BusyAdapter(), "openai": WorkingAdapter()}
    monkeypatch.setattr(provider_router, "_adapter_for", lambda provider, key: adapters[provider])
    router = RoutedOnboardingLLMProvider(
        [
            OnboardingProviderCandidate("google", "gemini-2.5-flash", "google-key"),
            OnboardingProviderCandidate("openai", "gpt-4o-mini", "openai-key"),
        ],
        health=ProviderHealth(redis=None, failure_threshold=10),
    )

    content, usage = await router.generate([], "automatic")

    assert content == '{"ok": true}'
    assert usage == 4
    assert router.last_provider == "openai"
    assert [item["status"] for item in router.last_attempts] == ["failed", "completed"]


@pytest.mark.asyncio
async def test_router_reports_fallback_failure_instead_of_earlier_rate_limit(monkeypatch) -> None:
    from app.services.onboarding import provider_router
    from app.services.provider_health import ProviderHealth

    class FailingAdapter:
        def __init__(self, status: int) -> None:
            self.status = status

        async def generate(self, **kwargs):
            request = httpx.Request("POST", "https://example.test/generate")
            response = httpx.Response(self.status, request=request)
            raise httpx.HTTPStatusError("provider failed", request=request, response=response)

    adapters = {"google": FailingAdapter(429), "openai": FailingAdapter(400)}
    monkeypatch.setattr(provider_router, "_adapter_for", lambda provider, key: adapters[provider])
    monkeypatch.setattr(provider_router.settings, "ONBOARDING_MAX_PROVIDER_ATTEMPTS", 2)
    router = RoutedOnboardingLLMProvider(
        [
            OnboardingProviderCandidate("google", "gemini-2.5-flash", "google-key"),
            OnboardingProviderCandidate("openai", "gpt-4o-mini", "openai-key"),
        ],
        health=ProviderHealth(redis=None, failure_threshold=10),
    )

    with pytest.raises(httpx.HTTPStatusError) as raised:
        await router.generate([], "automatic")

    assert raised.value.response.status_code == 400
    assert router.last_provider == "openai"
    assert router.last_model == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_openai_schema_rejection_retries_with_json_compatibility_mode(monkeypatch) -> None:
    from app.services import rag

    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    rejected = httpx.Response(
        400,
        request=request,
        json={
            "error": {
                "type": "invalid_request_error",
                "code": "invalid_json_schema",
                "param": "response_format",
                "message": "schema rejected",
            }
        },
    )
    completed = httpx.Response(
        200,
        request=request,
        json={
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": '{"text":"ok"}'},
                }
            ],
            "usage": {"total_tokens": 4},
        },
    )

    class FakeClient:
        calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            response = rejected if self.calls == 0 else completed
            self.calls += 1
            return response

    client = FakeClient()
    monkeypatch.setattr(rag.httpx, "AsyncClient", lambda **kwargs: client)
    provider = OpenAILLMProvider("openai-key")

    content, usage = await provider.generate(
        [{"role": "user", "content": "return JSON"}],
        "gpt-4o-mini",
        response_schema=onboarding_response_schema(),
    )

    assert content == '{"text":"ok"}'
    assert usage == 4
    assert client.calls == 2
    assert provider.last_status_code == 200
    assert provider.last_response_schema_applied is False
    assert provider.last_error_metadata["code"] == "invalid_json_schema"


@pytest.mark.asyncio
async def test_openai_onboarding_compatibility_mode_starts_with_json_object(monkeypatch) -> None:
    from app.services import rag

    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    completed = httpx.Response(
        200,
        request=request,
        json={
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": '{"text":"ok"}'},
                }
            ],
            "usage": {"total_tokens": 4},
        },
    )

    class FakeClient:
        captured: list[dict] = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            self.captured.append(kwargs["json"])
            return completed

    client = FakeClient()
    monkeypatch.setattr(rag.httpx, "AsyncClient", lambda **kwargs: client)
    provider = OpenAILLMProvider("openai-key", onboarding_compatibility_mode=True)

    content, usage = await provider.generate(
        [{"role": "user", "content": "return JSON"}],
        "gpt-4o-mini",
        response_schema=onboarding_response_schema(),
    )

    assert content == '{"text":"ok"}'
    assert usage == 4
    assert client.captured[0]["response_format"] == {"type": "json_object"}
    assert provider.last_response_schema_applied is False


@pytest.mark.asyncio
async def test_provider_429_is_cooled_down_for_the_current_session(monkeypatch) -> None:
    from app.services.onboarding import provider_router
    from app.services.provider_health import ProviderHealth

    class Trace:
        session_id = "session-429"

        def start_attempt(self, **kwargs):
            return "attempt"

        def finish_attempt(self, *args, **kwargs):
            return None

    class BusyAdapter:
        calls = 0

        async def generate(self, **kwargs):
            self.calls += 1
            request = httpx.Request("POST", "https://example.test/generate")
            response = httpx.Response(429, request=request)
            raise httpx.HTTPStatusError("busy", request=request, response=response)

    class WorkingAdapter:
        calls = 0

        async def generate(self, **kwargs):
            self.calls += 1
            return '{"ok": true}', 1

    busy = BusyAdapter()
    working = WorkingAdapter()
    adapters = {"google": busy, "openai": working}
    monkeypatch.setattr(provider_router, "current_trace", lambda: Trace())
    monkeypatch.setattr(provider_router, "_adapter_for", lambda provider, key: adapters[provider])
    monkeypatch.setattr(provider_router.settings, "ONBOARDING_MAX_PROVIDER_ATTEMPTS", 2)
    monkeypatch.setattr(provider_router.settings, "ONBOARDING_PROVIDER_COOLDOWN_SECONDS", 30)
    provider_router._SESSION_PROVIDER_COOLDOWNS.clear()

    candidates = [
        OnboardingProviderCandidate("google", "gemini-2.5-flash", "google-key"),
        OnboardingProviderCandidate("openai", "gpt-4o-mini", "openai-key"),
    ]
    health = ProviderHealth(redis=None, failure_threshold=10)
    first = RoutedOnboardingLLMProvider(candidates, health=health)
    second = RoutedOnboardingLLMProvider(candidates, health=health)

    await first.generate([], "automatic")
    await second.generate([], "automatic")

    assert busy.calls == 1
    assert working.calls == 2
    provider_router._SESSION_PROVIDER_COOLDOWNS.clear()


def test_openrouter_onboarding_model_is_pinned(monkeypatch) -> None:
    monkeypatch.setattr(provider_router.settings, "OPENROUTER_FALLBACK_MODEL", "openai/gpt-4o-mini")

    assert provider_router._model_for("openrouter", "google", "auto") == "openai/gpt-4o-mini"


def test_automatic_onboarding_priority_starts_with_openai() -> None:
    assert provider_router._PROVIDER_KEYS[0] == ("openai", "OPENAI_API_KEY")


@pytest.mark.asyncio
async def test_onboarding_router_bounds_provider_attempts(monkeypatch) -> None:
    from app.services.provider_health import ProviderHealth

    class FailingAdapter:
        async def generate(self, **kwargs):
            raise RuntimeError("provider unavailable")

    adapters = {name: FailingAdapter() for name in ("google", "openai", "openrouter")}
    monkeypatch.setattr(provider_router, "_adapter_for", lambda provider, key: adapters[provider])
    monkeypatch.setattr(provider_router.settings, "ONBOARDING_MAX_PROVIDER_ATTEMPTS", 2)

    router = RoutedOnboardingLLMProvider(
        [
            OnboardingProviderCandidate("google", "gemini-2.5-flash", "google-key"),
            OnboardingProviderCandidate("openai", "gpt-4o-mini", "openai-key"),
            OnboardingProviderCandidate("openrouter", "openai/gpt-4o-mini", "router-key"),
        ],
        health=ProviderHealth(redis=None, failure_threshold=10),
    )

    with pytest.raises(RuntimeError, match="provider unavailable"):
        await router.generate([], "automatic")

    assert len(router.last_attempts) == 2


@pytest.mark.asyncio
async def test_resume_requirements_get_adaptive_document_question() -> None:
    from app.services.onboarding.intelligence import RuleBasedRequirementsExtractor

    requirements = await RuleBasedRequirementsExtractor().extract(
        "I am building an AI resume analyzer for graduates"
    )
    question = AdaptiveClarificationService().next_question(requirements)

    assert question is not None
    assert question.requirement == "document_formats"


def test_runtime_plan_is_versioned_and_contains_inferred_components() -> None:
    requirements = ApplicationRequirements(
        application_type="resume_analyzer",
        primary_function="Analyze resumes",
        target_users=["graduates"],
        inputs=["resume"],
        outputs=["ATS score"],
        requires_documents=True,
        document_formats=["pdf", "docx"],
        requires_external_data=False,
        requires_tools=False,
        requires_memory=False,
    )
    generator = RuntimePlanGenerator()
    first = generator.generate(requirements, {"routing_strategy": "balanced"}, None)
    second = generator.generate(
        requirements,
        {"routing_strategy": "quality_optimized"},
        first.model_dump(mode="json"),
    )

    assert first.plan_version == 1
    assert second.plan_version == 2
    assert first.status == "validated"
    assert any(item.key == "document_processing" for item in first.components)
    assert any(item["integration_slug"] == "document_storage" for item in first.integration_policies)


def test_plan_does_not_invent_provider_or_connection_ownership() -> None:
    requirements = ApplicationRequirements(
        application_type="developer_ai_assistant",
        primary_function="Analyze supplied code context",
        target_users=["developers"],
        inputs=["code context"],
        outputs=["architecture findings"],
        requires_documents=False,
        requires_external_data=False,
        requires_tools=True,
        requires_memory=False,
        integrations=[{"slug": "github", "purpose": "Repository context"}],
    )

    plan = RuntimePlanGenerator().generate(requirements, {})

    assert plan.model_routing["provider"] == "automatic"
    assert plan.model_routing["model"] == "automatic"
    assert plan.integration_policies[0]["connection_mode"] is None
    assert "connection_ownership" in plan.unresolved_requirements


def test_complete_requirements_still_receive_contextual_checkpoint() -> None:
    requirements = ApplicationRequirements(
        application_type="ai_customer_support",
        primary_function="Answer customer questions and assist support workflows",
        target_users=["support agents", "customers"],
        inputs=["customer question"],
        outputs=["grounded support answer"],
        requires_documents=True,
        document_formats=["pdf"],
        requires_external_data=False,
        requires_tools=True,
        requires_memory=True,
        memory_scope="session",
        connection_ownership="company",
        integrations=[{"slug": "github", "purpose": "Support context"}],
    )

    service = AdaptiveClarificationService()
    question = service.next_conversation_question(requirements, set())

    assert question is not None
    assert question.requirement == "access_and_actions"
    assert "read-only" in question.question


def test_contextual_checkpoint_is_not_repeated_after_answer() -> None:
    requirements = ApplicationRequirements(
        application_type="developer_ai_assistant",
        primary_function="Analyze repository architecture",
        target_users=["developers"],
        inputs=["engineering question"],
        outputs=["architecture findings"],
        requires_documents=False,
        requires_external_data=False,
        requires_tools=False,
        requires_memory=False,
    )

    service = AdaptiveClarificationService()
    first = service.next_conversation_question(requirements, set())
    second = service.next_conversation_question(requirements, {"tool_permissions"})

    assert first is not None
    assert first.requirement == "tool_permissions"
    assert second is not None
    assert second.requirement == "external_retrieval_policy"


def test_unavailable_integrations_are_explained_without_entering_the_draft() -> None:
    proposed_data = {"integrations": ["bitbucket", "not_a_real_connector", "github"]}
    response = OnboardingModelResponse(
        text="I can configure the requested sources.",
        proposed_intent="select_integrations",
        proposed_data=proposed_data,
    )

    OnboardingEngine._filter_unavailable_integrations(proposed_data)
    OnboardingEngine._append_integration_availability_notice(response)

    assert proposed_data["integrations"] == ["github"]
    assert "Bitbucket" in proposed_data["coming_soon_integrations"]
    assert "not_a_real_connector" in proposed_data["unsupported_integrations"]
    assert "not supported by Zyntry yet" in response.text
    assert "coming soon" in response.text


def test_runtime_name_extractor_handles_create_named_prompt() -> None:
    """The common ``create a runtime named ...`` form must survive onboarding."""
    from app.services.onboarding.models import FastOnboardingModelProvider

    assert (
        FastOnboardingModelProvider._extract_runtime_name(
            "Create a runtime named LearnFlow Student Success Assistant.\n"
            "This runtime supports an online learning platform."
        )
        == "LearnFlow Student Success Assistant"
    )
    assert (
        FastOnboardingModelProvider._extract_runtime_name(
            "Name the runtime: Atlas Operations Assistant."
        )
        == "Atlas Operations Assistant"
    )


def test_runtime_name_survives_clarification_transition() -> None:
    """Clarification turns must not replace an explicit name with a default."""
    engine = OnboardingEngine.__new__(OnboardingEngine)
    config, state = engine._authorize_and_transition(
        current_state="onboarding_started",
        current_config={},
        proposed_intent="clarify_requirements",
        proposed_data={"runtime_name": "LearnFlow Student Success Assistant"},
    )

    assert state == "clarifying_requirements"
    assert config["runtime_name"] == "LearnFlow Student Success Assistant"


@pytest.mark.asyncio
async def test_architecture_prompt_does_not_infer_mentioned_connectors() -> None:
    """Explicitly excluded services must not leak into a new runtime plan."""
    from app.services.onboarding.intelligence import RuleBasedRequirementsExtractor

    requirements = await RuleBasedRequirementsExtractor().extract(
        "Create a company-managed architecture analysis runtime. "
        "Do not configure GitHub, Slack, or end-user OAuth; the host app will "
        "provide sanitized context and dependency graphs."
    )

    assert requirements.application_type == "architecture_analysis"
    assert requirements.integrations == []
    assert requirements.requires_tools is False
