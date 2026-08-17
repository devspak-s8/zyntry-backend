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
    session_id = session_data["id"]

    # 3. Message 1: Discovering Application Type & Integration Mode
    resp1 = await onboarding.send_chat_message(
        user_id=user.id,
        req=OnboardingMessageRequest(
            session_id=session_id,
            message="My end users will connect their own external GitHub and Slack accounts (Mode B)",
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

    # 5. Message 3: Confirming Configuration
    resp3 = await onboarding.send_chat_message(
        user_id=user.id,
        req=OnboardingMessageRequest(
            session_id=session_id,
            message="Use GPT-4o with balanced routing in development environment",
        ),
    )
    assert resp3.state == "confirming_configuration"
    assert resp3.proposed_runtime is not None

    # 6. Complete Onboarding: Provision Runtime
    complete_resp = await onboarding.complete_chat_onboarding(
        user_id=user.id,
        req=OnboardingCompleteRequest(
            session_id=session_id,
            runtime_name="Support Agent Runtime",
            environment="development",
        ),
    )
    assert complete_resp.status == "active"
    assert complete_resp.runtime_name == "Support Agent Runtime"
    assert len(complete_resp.enabled_integrations) == 2

    # Verify Runtime in database
    runtime_uuid = uuid.UUID(complete_resp.runtime_id)
    runtime = await uow.runtimes.get(runtime_uuid)
    assert runtime is not None
    assert runtime.user_id == user.id
    assert runtime.organization_id is None
    assert runtime.project_id is None

    # Verify Runtime Integrations are declared as supported capabilities
    r_integrations = await uow.runtime_integrations.get_by_runtime(runtime_uuid)
    assert len(r_integrations) == 2
    slugs = {ri.integration_slug for ri in r_integrations}
    assert slugs == {"github", "slack"}
    for ri in r_integrations:
        assert ri.connection_mode == "end_user_oauth"
        assert ri.connection_status == "not_connected"  # Capability is enabled, but no credentials attached yet

    # 7. Explicit API Key Creation (Decoupled Lifecycle)
    key_result = await apikey_service.create_key(
        user_id=user.id,
        data=ApiKeyCreate(
            name="Dev Backend Key",
            runtime_id=runtime_uuid,
            environment="development",
            scopes=["read", "write"],
        ),
    )
    assert key_result["api_key"].runtime_id == runtime_uuid
    assert key_result["raw_key"].startswith("sk_test_")

    # User creates a Production Key for the same runtime
    prod_key_result = await apikey_service.create_key(
        user_id=user.id,
        data=ApiKeyCreate(
            name="Production Key",
            runtime_id=runtime_uuid,
            environment="production",
            scopes=["read", "write"],
        ),
    )
    assert prod_key_result["api_key"].environment == "production"
    assert prod_key_result["raw_key"].startswith("sk_live_")
