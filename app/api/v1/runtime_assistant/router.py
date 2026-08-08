from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.core.database import get_session
from app.models.users import User
from app.schemas.runtime_assistant import AssistantChatRequest, AssistantChatResponse
from app.services.runtime_assistant.service import RuntimeAssistantService

router = APIRouter(prefix="/runtime-assistant", tags=["runtime-assistant"])


@router.post("/chat", response_model=AssistantChatResponse)
async def chat_with_assistant(
    body: AssistantChatRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    session: AsyncSession = Depends(get_session),
) -> AssistantChatResponse:
    service = RuntimeAssistantService(session)
    response = await service.chat(
        runtime_id=body.runtime_id,
        user_id=str(current_user.id),
        user_role="owner" if current_user.is_superuser else "developer",
        message=body.message,
        stream=body.stream,
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
    )


@router.get("/{runtime_id}/summary")
async def get_runtime_summary(
    runtime_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
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
) -> dict[str, Any]:
    service = RuntimeAssistantService(session)
    history = await service.get_chat_history(runtime_id=runtime_id, limit=limit)
    return {
        "runtime_id": runtime_id,
        "history": [
            {
                "role": msg.role,
                "content": msg.content,
                "timestamp": msg.timestamp.isoformat() if msg.timestamp else None,
            }
            for msg in history
        ],
    }


@router.get("/{runtime_id}/diagnostics")
async def run_diagnostics(
    runtime_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
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
