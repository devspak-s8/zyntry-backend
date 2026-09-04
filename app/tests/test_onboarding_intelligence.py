from __future__ import annotations

import pytest

from app.schemas.onboarding_intelligence import ApplicationRequirements
from app.services.onboarding.intelligence import (
    AdaptiveClarificationService,
    ModelBackedRequirementsExtractor,
    RuntimePlanGenerator,
)
from app.services.onboarding.engine import OnboardingEngine
from app.services.onboarding.models import OnboardingModelResponse


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
    assert requirements.extraction_source == "hybrid"


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
