from __future__ import annotations

import json
from typing import Any

import pytest

from app.schemas.onboarding_intelligence import ApplicationRequirements
from app.services.onboarding.engine import OnboardingEngine
from app.services.onboarding.intelligence import (
    AdaptiveClarificationService,
    ModelBackedRequirementsExtractor,
    OnboardingModelUnavailableError,
    RuleBasedRequirementsExtractor,
    RuntimePlanGenerator,
)
from app.services.onboarding.models import OnboardingModelResponse


def _requirements_payload(
    *,
    application_type: str,
    primary_function: str,
    target_users: list[str],
    inputs: list[str],
    outputs: list[str],
    integrations: list[str] | None = None,
    decisions: list[dict[str, str]] | None = None,
    requires_documents: bool = False,
    document_formats: list[str] | None = None,
    requires_external_data: bool = False,
    external_source_types: list[str] | None = None,
    requires_memory: bool = False,
    memory_scope: str | None = None,
    requires_tools: bool | None = None,
    connection_ownership: str | None = None,
    data_sensitivity: str = "internal",
) -> dict[str, Any]:
    direct = integrations or []
    return {
        "schema_version": "1.0",
        "application_type": application_type,
        "primary_function": primary_function,
        "target_users": target_users,
        "inputs": inputs,
        "outputs": outputs,
        "requires_documents": requires_documents,
        "document_formats": document_formats or [],
        "requires_external_data": requires_external_data,
        "external_source_types": external_source_types or [],
        "requires_tools": bool(direct) if requires_tools is None else requires_tools,
        "requires_memory": requires_memory,
        "memory_scope": memory_scope,
        "connection_ownership": connection_ownership if direct else None,
        "integrations": [
            {"slug": slug, "purpose": f"Direct {slug} access"}
            for slug in direct
        ],
        "integration_decisions": decisions or [
            {
                "slug": slug,
                "decision": "direct",
                "reason": "The runtime must access this source directly.",
            }
            for slug in direct
        ],
        "data_sensitivity": data_sensitivity,
        "confidence": 0.92,
    }


_SCENARIOS: list[tuple[str, str, dict[str, Any], list[str], str]] = [
    (
        "customer_support",
        "SCENARIO:customer_support Build a support assistant for agents.",
        _requirements_payload(
            application_type="ai_customer_support",
            primary_function="Answer customer questions and assist support workflows",
            target_users=["support agents", "customers"],
            inputs=["customer question", "account context"],
            outputs=["grounded support answer"],
            integrations=["postgresql", "slack"],
            requires_documents=True,
            document_formats=["pdf", "markdown"],
            requires_memory=True,
            memory_scope="session",
            connection_ownership="company",
        ),
        ["postgresql", "slack"],
        "validated",
    ),
    (
        "resume_screening",
        "SCENARIO:resume_screening Build a resume screening assistant.",
        _requirements_payload(
            application_type="resume_analyzer",
            primary_function="Compare resumes with job requirements",
            target_users=["recruiters"],
            inputs=["resume", "job description"],
            outputs=["structured candidate summary", "match score"],
            requires_documents=True,
            document_formats=["pdf", "docx"],
        ),
        [],
        "validated",
    ),
    (
        "architecture_context_only",
        "SCENARIO:architecture_context_only Analyze sanitized architecture context supplied by the host.",
        _requirements_payload(
            application_type="architecture_analysis",
            primary_function="Analyze software architecture using sanitized context and engineering graphs",
            target_users=["developers", "architects"],
            inputs=["engineering question", "sanitized code context", "dependency graph", "evidence references"],
            outputs=["architecture findings", "evidence references", "recommended follow-up"],
            decisions=[
                {"slug": "github", "decision": "host_managed", "reason": "The host supplies repository context."},
                {"slug": "gitlab", "decision": "host_managed", "reason": "The host supplies repository context."},
                {"slug": "bitbucket", "decision": "unsupported", "reason": "This connector is coming soon."},
            ],
            requires_tools=False,
        ),
        [],
        "validated",
    ),
    (
        "student_rag",
        "SCENARIO:student_rag Build a student knowledge assistant with private course data.",
        _requirements_payload(
            application_type="knowledge_search_rag",
            primary_function="Answer student questions from course knowledge",
            target_users=["students", "instructors"],
            inputs=["student question", "course context"],
            outputs=["grounded answer", "citations"],
            integrations=["postgresql", "redis", "website"],
            requires_documents=True,
            document_formats=["pdf", "docx"],
            requires_external_data=True,
            external_source_types=["approved domains only"],
            requires_memory=True,
            memory_scope="session",
            connection_ownership="company",
        ),
        ["postgresql", "redis", "website"],
        "validated",
    ),
    (
        "operations_analytics",
        "SCENARIO:operations_analytics Build a stateless operations analytics assistant.",
        _requirements_payload(
            application_type="general_ai_application",
            primary_function="Summarize operational business metrics",
            target_users=["operations managers"],
            inputs=["metric question"],
            outputs=["metric summary"],
            integrations=["mysql", "google_sheets"],
            requires_tools=True,
            connection_ownership="company",
        ),
        ["mysql", "google_sheets"],
        "validated",
    ),
    (
        "developer_assistant",
        "SCENARIO:developer_assistant Help developers investigate repositories and discussions.",
        _requirements_payload(
            application_type="developer_ai_assistant",
            primary_function="Answer development questions with repository context",
            target_users=["developers"],
            inputs=["developer question", "repository metadata"],
            outputs=["code explanation", "recommendation"],
            integrations=["github", "slack"],
            requires_tools=True,
            connection_ownership="company",
        ),
        ["github", "slack"],
        "validated",
    ),
    (
        "sales_knowledge",
        "SCENARIO:sales_knowledge Build a sales knowledge copilot.",
        _requirements_payload(
            application_type="knowledge_search_rag",
            primary_function="Answer sales-process questions from internal knowledge",
            target_users=["sales representatives"],
            inputs=["sales question"],
            outputs=["grounded answer"],
            integrations=["notion", "google_drive"],
            requires_documents=True,
            document_formats=["pdf", "markdown"],
            requires_memory=True,
            memory_scope="user",
            connection_ownership="company",
        ),
        ["notion", "google_drive"],
        "validated",
    ),
    (
        "legal_review",
        "SCENARIO:legal_review Review private contracts and policies.",
        _requirements_payload(
            application_type="document_analyzer",
            primary_function="Review contracts for obligations and risks",
            target_users=["legal team"],
            inputs=["contract document", "review question"],
            outputs=["risk summary", "clause references"],
            requires_documents=True,
            document_formats=["pdf", "docx"],
            data_sensitivity="confidential",
        ),
        [],
        "validated",
    ),
    (
        "hr_policy",
        "SCENARIO:hr_policy Answer employee policy questions from the company wiki.",
        _requirements_payload(
            application_type="knowledge_search_rag",
            primary_function="Answer employee policy questions",
            target_users=["employees"],
            inputs=["policy question"],
            outputs=["policy answer", "source references"],
            integrations=["confluence"],
            requires_documents=True,
            document_formats=["pdf", "markdown"],
            requires_memory=False,
            connection_ownership="company",
        ),
        ["confluence"],
        "validated",
    ),
    (
        "incident_response",
        "SCENARIO:incident_response Help incident responders correlate alerts and discussions.",
        _requirements_payload(
            application_type="autonomous_ai_agent",
            primary_function="Summarize incidents and recommend response steps",
            target_users=["incident responders"],
            inputs=["incident identifier", "operator question"],
            outputs=["incident summary", "recommended next step"],
            integrations=["slack", "jira"],
            requires_tools=True,
            requires_memory=True,
            memory_scope="session",
            connection_ownership="company",
        ),
        ["slack", "jira"],
        "validated",
    ),
    (
        "finance_reporting",
        "SCENARIO:finance_reporting Summarize internal finance exports.",
        _requirements_payload(
            application_type="general_ai_application",
            primary_function="Explain finance metrics from internal records",
            target_users=["finance managers"],
            inputs=["finance question", "CSV export"],
            outputs=["metric explanation"],
            integrations=["postgresql"],
            requires_documents=True,
            document_formats=["csv", "json"],
            requires_tools=True,
            connection_ownership="company",
            data_sensitivity="confidential",
        ),
        ["postgresql"],
        "validated",
    ),
    (
        "ecommerce_orders",
        "SCENARIO:ecommerce_orders Answer order questions using records and session state.",
        _requirements_payload(
            application_type="ai_customer_support",
            primary_function="Answer order-status questions",
            target_users=["customers", "support agents"],
            inputs=["order question", "order identifier"],
            outputs=["order answer"],
            integrations=["postgresql", "redis"],
            requires_tools=True,
            requires_memory=True,
            memory_scope="session",
            connection_ownership="company",
        ),
        ["postgresql", "redis"],
        "validated",
    ),
    (
        "research_assistant",
        "SCENARIO:research_assistant Research a topic using private notes and approved sources.",
        _requirements_payload(
            application_type="knowledge_search_rag",
            primary_function="Synthesize research notes and approved public sources",
            target_users=["researchers"],
            inputs=["research question", "notes"],
            outputs=["synthesis", "citations"],
            integrations=["website"],
            requires_documents=True,
            document_formats=["pdf", "markdown"],
            requires_external_data=True,
            external_source_types=["official technical sources"],
            connection_ownership="company",
        ),
        ["website"],
        "validated",
    ),
    (
        "multilingual_helpdesk",
        "SCENARIO:multilingual_helpdesk Translate and answer helpdesk questions from internal docs.",
        _requirements_payload(
            application_type="ai_customer_support",
            primary_function="Provide multilingual grounded helpdesk answers",
            target_users=["customers"],
            inputs=["question in any supported language"],
            outputs=["translated support answer"],
            integrations=["document_storage"],
            requires_documents=True,
            document_formats=["pdf", "docx", "markdown"],
            requires_memory=True,
            memory_scope="session",
            connection_ownership="company",
        ),
        [],
        "validated",
    ),
    (
        "data_engineering",
        "SCENARIO:data_engineering Explain warehouse schemas and safe read-only queries.",
        _requirements_payload(
            application_type="developer_ai_assistant",
            primary_function="Explain data schemas and query plans",
            target_users=["data engineers"],
            inputs=["schema question", "SQL query"],
            outputs=["query explanation", "optimization suggestion"],
            integrations=["postgresql", "mysql"],
            requires_tools=True,
            connection_ownership="company",
        ),
        ["postgresql", "mysql"],
        "validated",
    ),
    (
        "release_manager",
        "SCENARIO:release_manager Summarize release readiness from repository and team context.",
        _requirements_payload(
            application_type="developer_ai_assistant",
            primary_function="Summarize release readiness and risks",
            target_users=["release managers"],
            inputs=["release question", "repository context"],
            outputs=["release summary", "risk list"],
            integrations=["github", "slack", "jira"],
            requires_tools=True,
            requires_memory=True,
            memory_scope="session",
            connection_ownership="company",
        ),
        ["github", "slack", "jira"],
        "validated",
    ),
    (
        "compliance_audit",
        "SCENARIO:compliance_audit Find control evidence in private audit documents.",
        _requirements_payload(
            application_type="document_analyzer",
            primary_function="Map audit controls to supplied evidence",
            target_users=["compliance analysts"],
            inputs=["control question", "audit documents"],
            outputs=["evidence map", "gaps"],
            integrations=["google_drive"],
            requires_documents=True,
            document_formats=["pdf", "docx", "csv"],
            connection_ownership="company",
            data_sensitivity="regulated",
        ),
        ["google_drive"],
        "validated",
    ),
    (
        "healthcare_knowledge",
        "SCENARIO:healthcare_knowledge Answer staff questions from regulated clinical procedures.",
        _requirements_payload(
            application_type="knowledge_search_rag",
            primary_function="Answer staff questions from approved procedures",
            target_users=["clinical staff"],
            inputs=["procedure question"],
            outputs=["cited procedure answer"],
            integrations=["document_storage"],
            requires_documents=True,
            document_formats=["pdf", "docx"],
            data_sensitivity="regulated",
        ),
        [],
        "validated",
    ),
    (
        "mcp_tool_agent",
        "SCENARIO:mcp_tool_agent Use an approved MCP server for read-only internal tools.",
        _requirements_payload(
            application_type="autonomous_ai_agent",
            primary_function="Use approved MCP tools to answer operational questions",
            target_users=["operations team"],
            inputs=["operator question"],
            outputs=["tool-grounded answer"],
            integrations=["mcp"],
            requires_tools=True,
            connection_ownership="company",
        ),
        ["mcp"],
        "validated",
    ),
    (
        "stateless_writer",
        "SCENARIO:stateless_writer Draft product copy without external systems or memory.",
        _requirements_payload(
            application_type="general_ai_application",
            primary_function="Draft product copy from a supplied brief",
            target_users=["marketing team"],
            inputs=["product brief"],
            outputs=["draft copy"],
            requires_tools=False,
            requires_memory=False,
        ),
        [],
        "validated",
    ),
]


class ScenarioGemini:
    """Provider fixture that behaves like a structured Gemini response."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    async def generate(
        self,
        messages: list[dict[str, str]],
        model: str,
        max_tokens: int = 2048,
        temperature: float = 0.7,
    ) -> tuple[str, int]:
        request = json.loads(messages[-1]["content"])
        self.requests.append(request)
        assert request["integration_registry"]
        if "architecture_investigation" in json.dumps(request["conversation_history"]):
            key = "architecture_context_only"
        else:
            key = request["latest_message"].split("SCENARIO:", 1)[1].split()[0]
        payload = next(item[2] for item in _SCENARIOS if item[0] == key)
        return json.dumps(payload), 128


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "prompt", "_payload", "expected_integrations", "expected_status"),
    _SCENARIOS,
    ids=[item[0] for item in _SCENARIOS],
)
async def test_model_backed_onboarding_scenarios(
    name: str,
    prompt: str,
    _payload: dict[str, Any],
    expected_integrations: list[str],
    expected_status: str,
) -> None:
    provider = ScenarioGemini()
    history = [
        {"role": "assistant", "content": "What are you building?"},
        {"role": "user", "content": "I am exploring the requirements."},
        {"role": "user", "content": prompt},
    ]
    requirements = await ModelBackedRequirementsExtractor(provider=provider).extract(
        prompt,
        history=history,
    )
    plan = RuntimePlanGenerator().generate(
        requirements,
        {
            "provider": "google_gemini",
            "model": "gemini-2.5-flash",
            "routing_strategy": "balanced",
            "environment": "development",
        },
    )

    assert provider.requests[-1]["conversation_history"] == history
    assert requirements.application_type
    assert requirements.integration_slugs() == expected_integrations
    assert plan.status == expected_status
    assert plan.requirements_fingerprint == requirements.fingerprint()
    actual_direct = [
        item["integration_slug"]
        for item in plan.integration_policies
        if item["integration_slug"] != "document_storage"
    ]
    assert actual_direct == expected_integrations
    assert all(item.key for item in plan.components)


ARCHITECTURE_ANALYSIS_CONVERSATION = [
    {
        "role": "user",
        "content": (
            "Create a company-managed runtime named Architecture Analysis Runtime.\n\n"
            "It should analyze software architecture questions using sanitized code context, "
            "dependency graphs, call graphs, data-flow information, and evidence supplied by my "
            "application.\n\n"
            "Start with one task type: architecture_investigation.\n\n"
            "The runtime should assemble context, select the appropriate model, handle retries "
            "and fallbacks, track usage, and return structured findings with confidence, evidence "
            "references, and recommended follow-up actions.\n\n"
            "It must not invent findings, calculate final developer scores, or publish unverified "
            "evidence. If the supplied context is insufficient, return awaiting_context instead "
            "of guessing.\n\n"
            "Do not configure GitHub, Slack, customer-support workflows, or end-user OAuth. Keep "
            "the runtime read-only. Show me the proposed plan and ask for confirmation before "
            "creating it."
        ),
    },
    {
        "role": "assistant",
        "content": "What data sources should the runtime use?",
    },
    {
        "role": "user",
        "content": (
            "The runtime should receive sanitized code context, dependency graphs, call graphs, "
            "data-flow information, and evidence references from the host application. Do not "
            "connect directly to GitHub, GitLab, Bitbucket, CI/CD systems, or customer databases. "
            "Do not use end-user OAuth."
        ),
    },
    {
        "role": "assistant",
        "content": "Who will provide the runtime context?",
    },
    {
        "role": "user",
        "content": (
            "The platform backend will connect to the Zyntry runtime with a service credential. "
            "The runtime is read-only and returns structured findings for independent verification."
        ),
    },
]


@pytest.mark.asyncio
async def test_architecture_conversation_uses_full_history_and_host_managed_sources() -> None:
    provider = ScenarioGemini()
    extractor = ModelBackedRequirementsExtractor(provider=provider)
    requirements = await extractor.extract(
        ARCHITECTURE_ANALYSIS_CONVERSATION[-1]["content"],
        history=ARCHITECTURE_ANALYSIS_CONVERSATION,
    )

    assert provider.requests[-1]["conversation_history"] == ARCHITECTURE_ANALYSIS_CONVERSATION
    assert requirements.application_type == "architecture_analysis"
    assert requirements.integration_slugs() == []
    assert {item.slug: item.decision for item in requirements.integration_decisions} == {
        "github": "host_managed",
        "gitlab": "host_managed",
        "bitbucket": "unsupported",
    }

    engine = OnboardingEngine.__new__(OnboardingEngine)
    engine.requirements_extractor = extractor
    engine.clarification_service = AdaptiveClarificationService()
    engine.runtime_plan_generator = RuntimePlanGenerator()
    response = OnboardingModelResponse(
        text="I configured GitHub, GitLab, and Bitbucket.",
        proposed_intent="set_use_case_and_mode",
        proposed_data={
            "integrations": ["github", "gitlab", "bitbucket"],
            "capabilities": {},
            "integration_mode": "end_user_oauth",
        },
    )
    response, _ = await engine._apply_requirements_intelligence(
        ai_resp=response,
        message=ARCHITECTURE_ANALYSIS_CONVERSATION[-1]["content"],
        current_state="onboarding_started",
        current_config={},
        history=ARCHITECTURE_ANALYSIS_CONVERSATION,
    )
    OnboardingEngine._apply_explicit_integration_exclusions(
        response,
        ARCHITECTURE_ANALYSIS_CONVERSATION[2]["content"],
    )
    configuration = engine._attach_runtime_plan(
        {"application_requirements": response.proposed_data["application_requirements"]},
        previous_plan=None,
    )

    assert response.proposed_data["integrations"] == []
    assert configuration["runtime_plan"]["integration_policies"] == []
    assert "GitHub" not in response.text
    assert "GitLab" not in response.text


def test_plan_never_grants_non_direct_integration_decisions() -> None:
    payload = _SCENARIOS[2][2]
    requirements = ApplicationRequirements.model_validate(payload)
    plan = RuntimePlanGenerator().generate(requirements, {"routing_strategy": "balanced"})

    assert requirements.integration_slugs() == []
    assert plan.integration_policies == []
    assert all(not item.key.startswith("integration:") for item in plan.components)
    assert {item.slug: item.decision for item in plan.integration_decisions} == {
        "github": "host_managed",
        "gitlab": "host_managed",
        "bitbucket": "unsupported",
    }


@pytest.mark.asyncio
async def test_production_extractor_does_not_silently_use_rule_fallback() -> None:
    extractor = ModelBackedRequirementsExtractor(
        provider=ScenarioGemini(),
        fallback=RuleBasedRequirementsExtractor(),
    )
    extractor.provider = None

    with pytest.raises(OnboardingModelUnavailableError):
        await extractor.extract("Build a customer support assistant")
