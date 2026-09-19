from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import UnitOfWork
from app.schemas.onboarding_chat import (
    OnboardingCompleteRequest,
    OnboardingMessageRequest,
)
from app.services.onboarding import OnboardingService
from app.services.onboarding.engine import OnboardingEngine, OnboardingNameMismatchError


def test_runtime_creation_requires_explicit_confirmation() -> None:
    assert not OnboardingEngine._is_explicit_runtime_confirmation(
        message="yes",
        state="configuring_runtime",
        proposed_intent="execute_provisioning",
    )
    assert not OnboardingEngine._is_explicit_runtime_confirmation(
        message="yes, continue with available integrations",
        state="confirming_configuration",
        proposed_intent="execute_provisioning",
    )
    assert OnboardingEngine._is_explicit_runtime_confirmation(
        message="Confirm & Create Runtime",
        state="confirming_configuration",
        proposed_intent="clarify_requirements",
    )


@pytest.mark.asyncio
async def test_chat_onboarding_full_lifecycle(db_session: AsyncSession) -> None:
    uow = UnitOfWork(db_session)
    onboarding = OnboardingService(uow)

    # 1. Create a User without an organization (user-first onboarding)
    user = await uow.users.create(
        email="dev_architect@zyntry.space",
        name="Developer Architect",
        is_active=True,
    )
    await uow.commit()

    # 2. Create Chat Onboarding Session
    session_data = await onboarding.create_chat_session(
        user_id=user.id,
        initial_prompt="I want to build an AI support agent for my customers",
    )
    assert session_data["user_id"] == str(user.id)
    assert session_data["state"] == "discovering_application_type"
    assert len(session_data["suggested_actions"]) > 0
    session_id = session_data["id"]

    # 3. Message 1: Discovering Application Type & Integration Mode
    resp1 = await onboarding.send_chat_message(
        user_id=user.id,
        req=OnboardingMessageRequest(
            session_id=session_id,
            message="My end users will connect their own external accounts (Mode B)",
        ),
    )
    assert resp1.state == "selecting_integrations"
    assert resp1.configuration.get("integration_mode") == "end_user_oauth"

    # 4. Message 2: Selecting Integrations & Capabilities
    resp2 = await onboarding.send_chat_message(
        user_id=user.id,
        req=OnboardingMessageRequest(
            session_id=session_id,
            message="I need GitHub for file retrieval and Slack for message search",
        ),
    )
    assert resp2.state == "configuring_runtime"
    assert "github" in resp2.configuration.get("integrations", [])
    assert "slack" in resp2.configuration.get("integrations", [])

    # 5. Message 3: Configuring Runtime -> Preview
    resp3 = await onboarding.send_chat_message(
        user_id=user.id,
        req=OnboardingMessageRequest(
            session_id=session_id,
            message="Use GPT-4o with balanced routing in development environment",
        ),
    )
    assert resp3.state == "confirming_configuration"
    assert resp3.proposed_runtime is not None
    assert "Confirm & Create Runtime" in resp3.suggested_actions

    # 6. Message 4: User clicks or types 'Confirm & Create Runtime' directly in chat
    resp4 = await onboarding.send_chat_message(
        user_id=user.id,
        req=OnboardingMessageRequest(
            session_id=session_id,
            message="Confirm & Create Runtime",
        ),
    )
    assert resp4.is_complete is True
    assert resp4.state == "completed"
    assert "Runtime created" in resp4.response
    assert resp4.proposed_runtime is not None
    assert resp4.proposed_runtime["runtime_id"] is not None
    assert resp4.proposed_runtime["status"] == "preconfigured"
    created_runtime = await uow.runtimes.get(UUID(resp4.proposed_runtime["runtime_id"]))
    assert created_runtime is not None
    assert created_runtime.project_id is None
    assert created_runtime.name == resp4.proposed_runtime["runtime_name"]


@pytest.mark.asyncio
async def test_chat_onboarding_natural_engineer_agent_flow(db_session: AsyncSession) -> None:
    uow = UnitOfWork(db_session)
    onboarding = OnboardingService(uow)

    user = await uow.users.create(
        email="engineer_triage@zyntry.space",
        name="Engineer Triager",
        is_active=True,
    )
    await uow.commit()

    # 1. User starts with: Autonomous engineer agent that triages GitHub issues
    session_data = await onboarding.create_chat_session(
        user_id=user.id,
        initial_prompt="Autonomous engineer agent that triages GitHub issues.",
    )
    assert "github" in session_data["configuration"].get("integrations", [])
    session_id = session_data["id"]

    # 2. User clicks 'Not sure yet' or mentions multiple integrations
    resp1 = await onboarding.send_chat_message(
        user_id=user.id,
        req=OnboardingMessageRequest(
            session_id=session_id,
            message="GitHub, Slack, Notion and PostgreSQL",
        ),
    )
    assert resp1.state == "configuring_runtime"
    assert "github" in resp1.configuration.get("integrations", [])
    assert "slack" in resp1.configuration.get("integrations", [])
    assert "notion" in resp1.configuration.get("integrations", [])
    integs = resp1.configuration.get("integrations", [])
    assert "postgres" in integs or "postgresql" in integs

    # 3. User selects performance strategy
    resp2 = await onboarding.send_chat_message(
        user_id=user.id,
        req=OnboardingMessageRequest(
            session_id=session_id,
            message="Fast responses",
        ),
    )
    assert resp2.state == "confirming_configuration"
    assert "Confirm & Create Runtime" in resp2.suggested_actions

    # 4. User confirms
    resp3 = await onboarding.send_chat_message(
        user_id=user.id,
        req=OnboardingMessageRequest(
            session_id=session_id,
            message="Confirm & Create Runtime",
        ),
    )
    assert resp3.is_complete is True
    assert resp3.state == "completed"
    assert "Runtime created" in resp3.response
    assert resp3.proposed_runtime is not None
    assert resp3.proposed_runtime["runtime_id"] is not None


@pytest.mark.asyncio
async def test_onboarding_returns_an_adaptive_question_before_plan_confirmation(
    db_session: AsyncSession,
) -> None:
    uow = UnitOfWork(db_session)
    onboarding = OnboardingService(uow)
    user = await uow.users.create(
        email="adaptive_question@zyntry.space",
        name="Adaptive Question User",
        is_active=True,
    )
    await uow.commit()

    session = await onboarding.create_chat_session(user.id)
    response = await onboarding.send_chat_message(
        user.id,
        OnboardingMessageRequest(
            session_id=session["id"],
            message=(
                "Create a runtime named Atlas Customer Support Assistant. "
                "It should answer customer questions using private documents and PostgreSQL."
            ),
        ),
    )

    assert response.is_complete is False
    assert response.clarification_question is not None
    assert "Does this sound right" not in response.response
    assert response.clarification_question.question in response.response


@pytest.mark.asyncio
async def test_initial_prompt_preserves_explicit_runtime_name(
    db_session: AsyncSession,
) -> None:
    uow = UnitOfWork(db_session)
    onboarding = OnboardingService(uow)

    user = await uow.users.create(
        email="named_runtime_prompt@zyntry.space",
        name="Named Runtime Prompt User",
        is_active=True,
    )
    await uow.commit()

    session = await onboarding.create_chat_session(
        user_id=user.id,
        initial_prompt=(
            "Create a runtime named LearnFlow Student Success Assistant. "
            "It should support an online learning platform."
        ),
    )

    assert session["configuration"]["runtime_name"] == "LearnFlow Student Success Assistant"


@pytest.mark.asyncio
async def test_completion_requires_review_when_submitted_name_differs(
    db_session: AsyncSession,
) -> None:
    uow = UnitOfWork(db_session)
    onboarding = OnboardingService(uow)
    user = await uow.users.create(
        email="name_review@zyntry.space",
        name="Name Review User",
        is_active=True,
    )
    await uow.commit()
    session = await onboarding.create_chat_session(
        user_id=user.id,
        initial_prompt=(
            "Create a runtime named LearnFlow Student Success Assistant. "
            "It will support courses."
        ),
    )

    with pytest.raises(OnboardingNameMismatchError) as exc_info:
        await onboarding.complete_chat_onboarding(
            user.id,
            OnboardingCompleteRequest(
                session_id=session["id"],
                runtime_name="Different Runtime",
            ),
        )
    assert exc_info.value.saved_name == "LearnFlow Student Success Assistant"
    assert exc_info.value.requested_name == "Different Runtime"

    reviewed = await onboarding.complete_chat_onboarding(
        user.id,
        OnboardingCompleteRequest(
            session_id=session["id"],
            runtime_name="Different Runtime",
            name_reviewed=True,
        ),
    )
    assert reviewed.runtime_name == "Different Runtime"


@pytest.mark.asyncio
async def test_onboarding_completion_creates_one_idempotent_runtime(
    db_session: AsyncSession,
) -> None:
    uow = UnitOfWork(db_session)
    onboarding = OnboardingService(uow)
    user = await uow.users.create(
        email="idempotent_runtime@zyntry.space",
        name="Idempotent Runtime User",
        is_active=True,
    )
    await uow.commit()

    session = await onboarding.create_chat_session(
        user.id,
        initial_prompt="Create a runtime named Idempotent Support Assistant.",
    )
    request = OnboardingCompleteRequest(
        session_id=session["id"],
        runtime_name="Idempotent Support Assistant",
        environment="development",
    )

    first = await onboarding.complete_chat_onboarding(user.id, request)
    second = await onboarding.complete_chat_onboarding(user.id, request)

    assert first.runtime_id is not None
    assert second.runtime_id == first.runtime_id
    assert first.status == second.status == "preconfigured"
    runtime = await uow.runtimes.get_by_owner_and_name(user.id, "Idempotent Support Assistant")
    assert runtime is not None
    assert str(runtime.id) == first.runtime_id


@pytest.mark.asyncio
async def test_active_legacy_session_recovers_explicit_runtime_name(
    db_session: AsyncSession,
) -> None:
    uow = UnitOfWork(db_session)
    onboarding = OnboardingService(uow)

    user = await uow.users.create(
        email="legacy_named_runtime@zyntry.space",
        name="Legacy Named Runtime User",
        is_active=True,
    )
    await uow.onboarding_sessions.create(
        user_id=user.id,
        state="clarifying_requirements",
        messages=[
            {
                "role": "user",
                "content": "Create a runtime named LearnFlow Student Success Assistant.",
            }
        ],
        configuration={
            "use_case": "ai_customer_support",
            "runtime_name": "Ai Customer Support Runtime",
        },
    )
    await uow.commit()

    resumed = await onboarding.create_chat_session(user_id=user.id)

    assert resumed["configuration"]["runtime_name"] == "LearnFlow Student Success Assistant"


@pytest.mark.asyncio
async def test_chat_onboarding_reset_and_fresh_session(db_session: AsyncSession) -> None:
    uow = UnitOfWork(db_session)
    onboarding = OnboardingService(uow)

    user = await uow.users.create(email="reset_tester@zyntry.space", name="Reset Tester", is_active=True)
    await uow.commit()

    # Create initial session
    s1 = await onboarding.create_chat_session(user_id=user.id, initial_prompt="Old session prompt")
    s1_id = s1["id"]

    # Request reset
    s2 = await onboarding.create_chat_session(user_id=user.id, reset=True)
    assert s2["id"] != s1_id
    assert s2["state"] == "onboarding_started"
    assert len(s2["messages"]) == 1


@pytest.mark.asyncio
async def test_new_initial_prompt_replaces_stale_active_session(
    db_session: AsyncSession,
) -> None:
    """A changed prompt must not resume an unrelated active draft."""
    uow = UnitOfWork(db_session)
    onboarding = OnboardingService(uow)
    user = await uow.users.create(
        email="stale_prompt@zyntry.space",
        name="Stale Prompt User",
        is_active=True,
    )
    await uow.commit()

    old = await onboarding.create_chat_session(
        user_id=user.id,
        initial_prompt="Build a customer support assistant with GitHub and Slack.",
    )
    fresh = await onboarding.create_chat_session(
        user_id=user.id,
        initial_prompt=(
            "Create a company-managed runtime named Architecture Analysis Runtime. "
            "Do not configure GitHub or Slack; receive sanitized context and graphs."
        ),
    )

    assert fresh["id"] != old["id"]
    assert fresh["configuration"]["runtime_name"] == "Architecture Analysis Runtime"
    assert fresh["configuration"].get("integrations", []) == []


@pytest.mark.asyncio
async def test_existing_preconfigured_runtime_skips_first_time_onboarding(
    db_session: AsyncSession,
) -> None:
    uow = UnitOfWork(db_session)
    onboarding = OnboardingService(uow)

    user = await uow.users.create(
        email="existing_runtime@zyntry.space",
        name="Existing Runtime User",
        is_active=True,
    )
    runtime = await uow.runtimes.create(
        user_id=user.id,
        name="Existing Assistant",
        status="preconfigured",
    )
    await uow.commit()

    session = await onboarding.create_chat_session(user_id=user.id)

    assert session["state"] == "completed"
    assert session["is_complete"] is True
    assert session["created_runtime_id"] == str(runtime.id)
    assert session["configuration"]["runtime_status"] == "preconfigured"
