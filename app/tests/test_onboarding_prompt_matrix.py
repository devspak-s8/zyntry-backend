from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest

from app.services.model_providers.base import UsageCallback
from app.services.onboarding.engine import OnboardingEngine
from app.services.onboarding.intelligence import (
    AdaptiveClarificationService,
    ModelBackedRequirementsExtractor,
    RuleBasedRequirementsExtractor,
    RuntimePlanGenerator,
)
from app.services.onboarding.models import OnboardingModelResponse
from app.services.rag import BaseLLMProvider

_PLAN_CONFIGURATION = {
    "provider": "google_gemini",
    "model": "gemini-2.5-flash",
    "routing_strategy": "balanced",
    "environment": "development",
}


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        pytest.param(
            (
                "Build a customer support assistant for our support team. "
                "Answer customer questions using private company PDF documents and "
                "PostgreSQL records, remember the current session, and let agents "
                "send Slack messages only after confirmation. Use company-managed "
                "connections and keep the runtime read-only by default."
            ),
            {
                "application_type": "ai_customer_support",
                "integrations": {"postgresql", "slack"},
                "requires_documents": True,
                "requires_memory": True,
                "plan_status": "validated",
            },
            id="customer-support-with-private-sources",
        ),
        pytest.param(
            (
                "Build a resume screening assistant for recruiters. Users upload "
                "PDF and DOCX resumes and receive structured candidate summaries. "
                "Use no external data and no connected systems."
            ),
            {
                "application_type": "resume_analyzer",
                "integrations": set(),
                "requires_documents": True,
                "requires_memory": False,
                "plan_status": "validated",
            },
            id="document-analysis-without-connectors",
        ),
        pytest.param(
            (
                "Create a company-managed architecture analysis assistant for "
                "developers. It receives sanitized code context, dependency graphs, "
                "call graphs, and evidence references. Do not configure GitHub, "
                "Slack, or end-user OAuth."
            ),
            {
                "application_type": "architecture_analysis",
                "integrations": set(),
                "requires_documents": False,
                "requires_memory": False,
                "plan_status": "validated",
            },
            id="architecture-context-only",
        ),
        pytest.param(
            (
                "Build a student knowledge assistant using private company course "
                "documents in PDF and DOCX, PostgreSQL enrollment records, and Redis "
                "progress data. Use private data first, then approved public "
                "websites when external retrieval is enabled, cite external claims, "
                "and remember the current session. Use company-managed connections."
            ),
            {
                "application_type": "knowledge_search_rag",
                "integrations": {"postgresql", "redis", "website"},
                "requires_documents": True,
                "requires_external_data": True,
                "requires_memory": True,
                "memory_scope": "session",
                "plan_status": "validated",
            },
            id="knowledge-rag-with-internal-first-retrieval",
        ),
        pytest.param(
            (
                "Create an analytics assistant for operations managers. Query MySQL "
                "and Google Sheets in read-only mode, summarize business metrics, "
                "use internal company data only, and keep each request stateless."
            ),
            {
                "application_type": "general_ai_application",
                "integrations": {"mysql", "google_sheets"},
                "requires_external_data": False,
                "requires_memory": False,
                "plan_status": "clarification_required",
                "clarification": True,
            },
            id="analytics-clarifies-missing-document-policy",
        ),
    ],
)
@pytest.mark.asyncio
async def test_onboarding_prompt_matrix_produces_safe_requirements_and_plan(
    prompt: str,
    expected: dict[str, object],
) -> None:
    """Exercise varied onboarding descriptions through extraction and planning.

    This matrix is intentionally provider-free so CI catches regressions in the
    response/plan contract even when no onboarding model key is configured.
    """
    requirements = await RuleBasedRequirementsExtractor().extract(prompt)
    plan = RuntimePlanGenerator().generate(requirements, _PLAN_CONFIGURATION, None)

    assert requirements.application_type == expected["application_type"]
    assert set(requirements.integration_slugs()) == expected["integrations"]
    for field in (
        "requires_documents",
        "requires_external_data",
        "requires_memory",
        "memory_scope",
    ):
        if field in expected:
            assert getattr(requirements, field) == expected[field]

    assert plan.status == expected["plan_status"]
    assert plan.application_type == requirements.application_type
    assert plan.requirements_fingerprint == requirements.fingerprint()
    assert plan.model_routing["provider"] == "google_gemini"
    assert plan.deployment["environment"] == "development"
    assert all(component.key for component in plan.components)

    if expected.get("clarification"):
        question = AdaptiveClarificationService().next_question(requirements)
        assert question is not None
        assert question.requirement in plan.unresolved_requirements
    else:
        assert not plan.unresolved_requirements


class _HallucinatingRequirementsModel(BaseLLMProvider):
    async def generate(self, messages, model, max_tokens=2048, temperature=0.7):
        # Simulate a model copying mentioned services into its proposal even
        # though the user explicitly excluded direct integrations.
        return (
            '{"schema_version":"1.0","application_type":"architecture_analysis",'
            '"primary_function":"Analyze supplied architecture context",'
            '"target_users":["developers"],"inputs":["sanitized context"],'
            '"outputs":["architecture findings"],"requires_documents":false,'
            '"requires_external_data":false,"requires_tools":true,'
            '"requires_memory":false,"integrations":['
            '{"slug":"github"},{"slug":"slack"}],"confidence":0.9}',
            32,
        )

    def astream(
        self,
        messages: list[dict[str, str]],
        model: str,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        on_usage: UsageCallback | None = None,
    ) -> AsyncGenerator[str]:
        async def _empty_stream() -> AsyncGenerator[str]:
            if False:
                yield ""

        return _empty_stream()


@pytest.mark.asyncio
async def test_explicit_connector_exclusions_override_model_and_plan() -> None:
    """Mentioning a connector in a prohibition must not enable that connector."""
    prompt = (
        "Create an architecture analysis assistant. Do not configure GitHub or "
        "Slack; the host application supplies sanitized context and graphs."
    )
    requirements = await ModelBackedRequirementsExtractor(
        provider=_HallucinatingRequirementsModel()
    ).extract(prompt)

    assert requirements.integration_slugs() == []
    assert requirements.requires_tools is False

    plan = RuntimePlanGenerator().generate(requirements, _PLAN_CONFIGURATION, None)
    assert plan.integration_policies == []
    assert all(not component.key.startswith("integration:") for component in plan.components)


def test_explicit_connector_exclusions_rewrite_stale_response_text() -> None:
    response = OnboardingModelResponse(
        text="Configured the architecture assistant with GitHub and Slack.",
        proposed_intent="set_use_case_and_mode",
        proposed_data={
            "use_case": "architecture_analysis",
            "application_type": "internal_ai_agent",
            "integrations": ["github", "slack"],
            "capabilities": {"github": ["repository_search"], "slack": ["message_search"]},
        },
    )

    OnboardingEngine._apply_explicit_integration_exclusions(response, "Do not configure GitHub or Slack.")

    assert response.proposed_data["integrations"] == []
    assert response.proposed_data["capabilities"] == {}
    assert "without direct integrations" in response.text
    assert "GitHub and Slack" not in response.text
