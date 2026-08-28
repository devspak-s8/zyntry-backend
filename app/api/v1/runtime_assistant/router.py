from __future__ import annotations

import uuid
import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.api.v1.dependencies_tenant import require_project_membership
from app.core.database import get_session
from app.models.runtimes import Runtime
from app.models.users import User
from app.schemas.runtime_assistant import (
    AssistantActionConfirmationRequest,
    AssistantActionProposalRequest,
    AssistantChatRequest,
    AssistantChatResponse,
)
from app.repositories import UnitOfWork
from app.services.runtime_assistant.commands import RuntimeAssistantCommandService
from app.services.runtime_assistant.records import RuntimeAssistantRecords
from app.services.runtime_assistant.schemas import UserRole
from app.services.runtime_assistant.service import RuntimeAssistantService

router = APIRouter(prefix="/runtime-assistant", tags=["runtime-assistant"])
logger = logging.getLogger(__name__)


def _user_role(current_user: User) -> UserRole:
    return UserRole.OWNER if current_user.is_superuser else UserRole.DEVELOPER


async def _authorize_runtime(
    runtime_id: str, current_user: User, session: AsyncSession
) -> Runtime:
    try:
        parsed_id = uuid.UUID(runtime_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid runtime id") from None
    runtime = await session.get(Runtime, parsed_id)
    if runtime is None:
        raise HTTPException(status_code=404, detail="Runtime not found")
    if not runtime.project_id:
        raise HTTPException(status_code=409, detail="Attach this runtime to a project before using Runtime Assistant")
    await require_project_membership(str(runtime.project_id), current_user, session)
    return runtime


@router.post("/chat", response_model=AssistantChatResponse)
async def chat_with_assistant(
    body: AssistantChatRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    session: AsyncSession = Depends(get_session),
) -> AssistantChatResponse:
    await _authorize_runtime(body.runtime_id, current_user, session)
    service = RuntimeAssistantService(session)
    response = await service.chat(
        runtime_id=body.runtime_id,
        user_id=str(current_user.id),
        user_role="owner" if current_user.is_superuser else "developer",
        message=body.message,
        stream=False,
        conversation_id=body.conversation_id,
    )
    if isinstance(response, dict):
        return AssistantChatResponse(**response)
    return AssistantChatResponse(
        message=response.message,
        tool_calls=response.tool_calls,
        diagnostics=response.diagnostics,
        optimizations=response.optimizations,
        summary=response.summary,
        metadata=response.metadata,
        conversation_id=response.metadata.get("conversation_id"),
    )


@router.get("/{runtime_id}/summary")
async def get_runtime_summary(
    runtime_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _authorize_runtime(runtime_id, current_user, session)
    service = RuntimeAssistantService(session)
    return await service.get_runtime_summary(
        runtime_id=runtime_id,
        user_id=str(current_user.id),
    )


@router.get("/{runtime_id}/history")
async def get_chat_history(
    runtime_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    session: AsyncSession = Depends(get_session),
    limit: int = 20,
    conversation_id: str | None = None,
) -> dict[str, Any]:
    await _authorize_runtime(runtime_id, current_user, session)
    service = RuntimeAssistantService(session)
    history = await service.get_chat_history(
        runtime_id=runtime_id,
        user_id=str(current_user.id),
        limit=limit,
        conversation_id=conversation_id,
    )
    return {
        "runtime_id": runtime_id,
        "history": [
            {
                "role": msg.role,
                "content": msg.content,
                "timestamp": msg.timestamp.isoformat() if msg.timestamp else None,
                "metadata": msg.metadata,
            }
            for msg in history
        ],
    }


@router.post("/chat/stream")
async def stream_assistant_chat(
    body: AssistantChatRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    await _authorize_runtime(body.runtime_id, current_user, session)

    async def events():
        def encode(event: str, data: dict[str, Any]) -> str:
            return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"

        yield encode("progress", {"stage": "loading_context", "message": "Loading runtime context"})
        service = RuntimeAssistantService(session)
        yield encode("progress", {"stage": "investigating", "message": "Querying runtime evidence"})
        try:
            response = await service.chat(
                runtime_id=body.runtime_id,
                user_id=str(current_user.id),
                user_role="owner" if current_user.is_superuser else "developer",
                message=body.message,
                stream=False,
                conversation_id=body.conversation_id,
            )
            payload = AssistantChatResponse(
                message=response.message,
                tool_calls=response.tool_calls,
                diagnostics=response.diagnostics,
                optimizations=response.optimizations,
                summary=response.summary,
                metadata=response.metadata,
                conversation_id=response.metadata.get("conversation_id"),
            ).model_dump(mode="json")
            yield encode("result", payload)
            yield encode("done", {"conversation_id": payload.get("conversation_id")})
        except Exception:
            logger.exception(
                "Runtime Assistant streamed investigation failed",
                extra={"runtime_id": body.runtime_id, "user_id": str(current_user.id)},
            )
            yield encode(
                "error",
                {"message": "Runtime investigation failed. No changes were applied."},
            )

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{runtime_id}/conversations")
async def list_conversations(
    runtime_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    session: AsyncSession = Depends(get_session),
    limit: int = 20,
) -> dict[str, Any]:
    await _authorize_runtime(runtime_id, current_user, session)
    records = RuntimeAssistantRecords(session)
    conversations = await records.list_conversations(
        uuid.UUID(runtime_id), current_user.id, limit
    )
    return {
        "conversations": [
            {
                "id": str(item.id),
                "title": item.title,
                "environment": item.environment,
                "status": item.status,
                "created_at": item.created_at.isoformat(),
                "updated_at": item.updated_at.isoformat(),
            }
            for item in conversations
        ]
    }


@router.delete("/{runtime_id}/conversations/{conversation_id}")
async def clear_conversation(
    runtime_id: str,
    conversation_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _authorize_runtime(runtime_id, current_user, session)
    try:
        parsed = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid conversation id") from None
    deleted = await RuntimeAssistantRecords(session).clear(
        parsed, uuid.UUID(runtime_id), current_user.id
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found")
    await session.commit()
    return {"status": "cleared", "conversation_id": conversation_id}


@router.post("/actions/propose")
async def propose_action(
    body: AssistantActionProposalRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    runtime = await _authorize_runtime(body.runtime_id, current_user, session)
    service = RuntimeAssistantCommandService(UnitOfWork(session))
    try:
        proposal = await service.propose(
            runtime_id=runtime.id,
            project_id=runtime.project_id,
            user_id=current_user.id,
            user_role=_user_role(current_user),
            action=body.action,
            arguments=body.arguments,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return {
        "id": str(proposal.id),
        "action": proposal.action,
        "target": str(runtime.id),
        "current_state": runtime.status,
        "proposed_change": proposal.arguments,
        "potential_impact": proposal.risk,
        "expires_at": proposal.expires_at.isoformat(),
        "status": proposal.status,
    }


@router.post("/actions/{proposal_id}/confirm")
async def confirm_action(
    proposal_id: str,
    body: AssistantActionConfirmationRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    runtime = await _authorize_runtime(body.runtime_id, current_user, session)
    try:
        parsed_proposal = uuid.UUID(proposal_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid proposal id") from None
    try:
        return await RuntimeAssistantCommandService(UnitOfWork(session)).resolve(
            proposal_id=parsed_proposal,
            runtime_id=runtime.id,
            project_id=runtime.project_id,
            user_id=current_user.id,
            user_role=_user_role(current_user),
            confirm=body.confirm,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.get("/{runtime_id}/diagnostics")
async def run_diagnostics(
    runtime_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _authorize_runtime(runtime_id, current_user, session)
    service = RuntimeAssistantService(session)
    results = await service.run_diagnostics(
        runtime_id=runtime_id,
        user_id=str(current_user.id),
        user_role="owner" if current_user.is_superuser else "developer",
    )
    return {
        "runtime_id": runtime_id,
        "diagnostics": [
            {
                "issue": r.issue,
                "severity": r.severity,
                "description": r.description,
                "affected_components": r.affected_components,
                "recommendations": r.recommendations,
                "metrics": r.metrics,
            }
            for r in results
        ],
    }


@router.get("/{runtime_id}/recommendations")
async def get_recommendations(
    runtime_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _authorize_runtime(runtime_id, current_user, session)
    service = RuntimeAssistantService(session)
    results = await service.get_recommendations(
        runtime_id=runtime_id,
        user_id=str(current_user.id),
    )
    return {
        "runtime_id": runtime_id,
        "recommendations": [
            {
                "category": r.category,
                "title": r.title,
                "description": r.description,
                "impact": r.impact,
                "estimated_savings": r.estimated_savings,
                "actions": r.actions,
                "priority": r.priority,
            }
            for r in results
        ],
    }
