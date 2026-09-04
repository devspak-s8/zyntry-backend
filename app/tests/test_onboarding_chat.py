from __future__ import annotations

import uuid
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.users import User
from app.repositories import UnitOfWork
from app.schemas.apikeys import ApiKeyCreate
from app.schemas.onboarding_chat import (
    OnboardingCompleteRequest,
    OnboardingMessageRequest,
)
from app.services.apikeys import ApiKeyService
from app.services.onboarding import OnboardingService
from app.services.onboarding.engine import OnboardingNameMismatchError


@pytest.mark.asyncio
async def test_chat_onboarding_full_lifecycle(db_session: AsyncSession) -> None:
    uow = UnitOfWork(db_session)
    onboarding = OnboardingService(uow)
    apikey_service = ApiKeyService(db_session)

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
    assert "Configuration draft saved" in resp4.response
    assert resp4.proposed_runtime is not None
    assert resp4.proposed_runtime["runtime_id"] is None
    assert resp4.proposed_runtime["status"] == "draft"


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
    assert "Configuration draft saved" in resp3.response


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
    session = await uow.onboarding_sessions.create(
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
