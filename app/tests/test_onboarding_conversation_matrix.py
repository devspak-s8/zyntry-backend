from __future__ import annotations

import pytest

from app.services.onboarding.intelligence import (
    RuleBasedRequirementsExtractor,
    RuntimePlanGenerator,
)

# These are deliberately short, realistic first-turn descriptions. The matrix
# is provider-free so CI can exercise onboarding breadth without spending model
# quota. Each case is followed by a contextual turn to verify that accumulated
# requirements survive the next answer.
_PROMPTS: tuple[tuple[str, str, str], ...] = (
    ("support_orders", "Build a customer support assistant that answers order-status questions.", "ai_customer_support"),
    ("support_tickets", "Create a helpdesk assistant for customer support tickets and replies.", "ai_customer_support"),
    ("support_agents", "Help support agents investigate customer account questions.", "ai_customer_support"),
    ("support_billing", "Build a billing support assistant for customer payment questions.", "ai_customer_support"),
    ("support_returns", "Answer customer questions about returns and refunds with a support assistant.", "ai_customer_support"),
    ("support_product", "Create product support chat for customers troubleshooting devices.", "ai_customer_support"),
    ("support_account", "Build an account recovery customer-support helper for our service team.", "ai_customer_support"),
    ("support_multilingual", "Provide multilingual customer service answers for a global helpdesk.", "ai_customer_support"),
    ("support_escalation", "Assist customer support staff with escalation summaries and next steps.", "ai_customer_support"),
    ("support_faq", "Create a customer FAQ support assistant grounded in our policies.", "ai_customer_support"),
    ("knowledge_internal", "Build an internal employee knowledge assistant for company policies.", "knowledge_search_rag"),
    ("knowledge_search", "Search our private knowledge base and answer employee questions.", "knowledge_search_rag"),
    ("knowledge_research", "Create a research assistant that finds answers in private notes.", "knowledge_search_rag"),
    ("knowledge_rag", "Build a RAG knowledge assistant for technical documentation.", "knowledge_search_rag"),
    ("knowledge_course", "Create a course-material study assistant for university students.", "knowledge_search_rag"),
    ("knowledge_handbook", "Answer staff questions by searching the company handbook.", "knowledge_search_rag"),
    ("knowledge_sales", "Build a sales knowledge assistant for representatives and playbooks.", "knowledge_search_rag"),
    ("knowledge_legal", "Search private legal knowledge and explain policy obligations.", "knowledge_search_rag"),
    ("knowledge_compliance", "Find compliance guidance in our internal knowledge repository.", "knowledge_search_rag"),
    ("knowledge_notes", "Search meeting notes and return cited knowledge to the team.", "knowledge_search_rag"),
    ("developer_code", "Build a developer assistant that explains code and suggests fixes.", "developer_ai_assistant"),
    ("developer_review", "Create a code review helper for pull requests.", "developer_ai_assistant"),
    ("developer_repository", "Help developers answer questions about a repository.", "developer_ai_assistant"),
    ("developer_sql", "Build a developer tool that explains SQL schemas and queries.", "developer_ai_assistant"),
    ("developer_api", "Create an API documentation assistant for software engineers.", "developer_ai_assistant"),
    ("developer_ci", "Help developers diagnose CI failures and propose code changes.", "developer_ai_assistant"),
    ("developer_release", "Build a release engineering assistant for repository readiness.", "developer_ai_assistant"),
    ("developer_debug", "Create a coding assistant that investigates runtime errors.", "developer_ai_assistant"),
    ("developer_dependencies", "Help developers understand dependency updates in their codebase.", "developer_ai_assistant"),
    ("developer_github", "Build a developer assistant for GitHub issues and repository context.", "autonomous_issue_triage_agent"),
    ("architecture_analysis", "Analyze software architecture and service boundaries.", "architecture_analysis"),
    ("architecture_investigation", "Create an architecture investigation assistant for engineers.", "architecture_analysis"),
    ("architecture_call_graph", "Investigate architecture using call graphs and service dependencies.", "architecture_analysis"),
    ("architecture_dependency", "Analyze a dependency graph to find architecture risks.", "architecture_analysis"),
    ("architecture_data_flow", "Review software architecture with data-flow information.", "architecture_analysis"),
    ("architecture_design", "Build an architecture design review assistant.", "architecture_analysis"),
    ("architecture_topology", "Explain system topology and architecture trade-offs.", "architecture_analysis"),
    ("architecture_engineering_graph", "Use engineering graphs to investigate architecture questions.", "architecture_analysis"),
    ("architecture_services", "Compare microservice architecture options for our platform.", "architecture_analysis"),
    ("architecture_api", "Review API architecture and identify integration risks.", "architecture_analysis"),
    ("resume_screening", "Build a resume screening assistant for recruiters.", "resume_analyzer"),
    ("resume_feedback", "Create a resume analyzer that gives candidates feedback.", "resume_analyzer"),
    ("cv_matching", "Match CVs to job descriptions and summarize the results.", "resume_analyzer"),
    ("ats_scoring", "Build an ATS resume scoring tool for hiring teams.", "resume_analyzer"),
    ("candidate_review", "Review uploaded resumes and produce candidate summaries.", "resume_analyzer"),
    ("issue_triage", "Create an issue triage agent for GitHub engineering tickets.", "autonomous_issue_triage_agent"),
    ("github_triage", "Triage GitHub issues and recommend owners for the engineering team.", "autonomous_issue_triage_agent"),
    ("incident_triage", "Build an issue triage assistant for production incident reports.", "autonomous_issue_triage_agent"),
    ("operations_agent", "Create an autonomous agent for read-only operations questions.", "autonomous_ai_agent"),
    ("marketing_writer", "Draft product marketing copy from a supplied brief.", "general_ai_application"),
)


def test_onboarding_prompt_matrix_has_at_least_fifty_cases() -> None:
    assert len(_PROMPTS) >= 50


@pytest.mark.asyncio
@pytest.mark.parametrize("name,prompt,expected_type", _PROMPTS, ids=[item[0] for item in _PROMPTS])
async def test_fifty_onboarding_prompts_preserve_context_and_generate_plans(
    name: str,
    prompt: str,
    expected_type: str,
) -> None:
    """Exercise varied onboarding turns without making provider requests."""
    extractor = RuleBasedRequirementsExtractor()
    requirements = await extractor.extract(prompt)
    first_function = requirements.primary_function

    # A second turn must enrich the same conversation, not reset its category
    # or purpose when the model receives a short contextual answer.
    requirements = await extractor.extract(
        "Keep the same purpose and audience. Make it read-only, private to the project, "
        "disable external retrieval, and remember relevant context within the current conversation.",
        current=requirements,
    )
    plan = RuntimePlanGenerator().generate(
        requirements,
        {"routing_strategy": "balanced", "environment": "development"},
    )

    assert requirements.application_type == expected_type, name
    assert requirements.primary_function == first_function, name
    assert requirements.requires_memory is True, name
    assert requirements.memory_scope == "session", name
    assert requirements.requires_external_data is False, name
    assert plan.application_type == expected_type, name
    assert plan.requirements_fingerprint == requirements.fingerprint(), name
    assert all(component.key for component in plan.components), name


@pytest.mark.asyncio
async def test_contextual_followups_merge_document_privacy_and_read_only_requirements() -> None:
    extractor = RuleBasedRequirementsExtractor()
    requirements = await extractor.extract(
        "Create an internal knowledge assistant using private PDF and DOCX files "
        "and company-managed PostgreSQL records."
    )

    requirements = await extractor.extract(
        "Keep uploads private to this project, use PostgreSQL read-only, and disable external retrieval.",
        current=requirements,
    )

    assert requirements.application_type == "knowledge_search_rag"
    assert requirements.requires_documents is True
    assert set(requirements.document_formats) == {"pdf", "docx"}
    assert requirements.requires_external_data is False
    assert requirements.requires_tools is True
    assert requirements.connection_ownership == "company"
    assert "postgresql" in requirements.integration_slugs()
