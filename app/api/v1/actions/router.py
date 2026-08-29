from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from app.api.v1.dependencies import get_current_user
from app.api.v1.dependencies_api_key import ActionAuthContext, get_action_auth
from app.api.v1.dependencies_tenant import require_project_membership
from app.core.database import get_session
from app.models.actions import ActionExecution
from app.models.users import User
from app.repositories import UnitOfWork
from app.schemas.actions import (
    ActionExecutionRead,
    ActionRequest,
    ActionResponse,
    WorkflowRequest,
)
from app.services.actions.confirmations import ConfirmationService
from app.services.actions.executor import ActionExecutor
from app.services.actions.guardrails import GuardrailService

router = APIRouter(prefix="/actions", tags=["actions"])


@router.get("/available", response_model=list[dict])
async def list_available_actions(
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[dict]:
    from app.services.actions.registry import ActionRegistry
    actions = ActionRegistry.list_actions()
    return [a.model_dump() for a in actions]


@router.post("/execute", response_model=ActionResponse)
async def execute_action(
    body: ActionRequest,
    auth: Annotated[ActionAuthContext, Depends(get_action_auth)],
    db: AsyncSession = Depends(get_session),
) -> ActionResponse:
    if auth.api_key and "write" not in set(auth.api_key.scopes or []) and "*" not in set(auth.api_key.scopes or []):
        raise HTTPException(status_code=403, detail="API key lacks write scope")
    uow = UnitOfWork(db)
    executor = ActionExecutor(uow)

    valid, error = GuardrailService.validate_action_arguments(
        body.provider, body.action, body.arguments
    )
    if not valid:
        raise HTTPException(status_code=400, detail=error)

    project_id = auth.project_id or uuid.UUID(body.project_id)
    project = await require_project_membership(str(project_id), auth.user, db)
    if auth.project_id is not None and auth.project_id != project.id:
        raise HTTPException(status_code=403, detail="API key is not authorized for this project")
    user_id = auth.user.id

    risk_actions = {"delete", "remove", "archive", "merge", "close", "cancel", "expire", "revoke"}
    requires_confirmation = any(risk in body.action.lower() for risk in risk_actions)

    if requires_confirmation and not body.confirm:
        confirmation_service = ConfirmationService(uow)
        high_risk = any(d in body.action.lower() for d in ["delete", "remove", "archive"])
        confirmation = await confirmation_service.request(
            user_id=user_id,
            project_id=project_id,
            provider=body.provider,
            action=body.action,
            arguments=body.arguments,
            risk="high" if high_risk else "medium",
        )
        return ActionResponse(
            success=False,
            error="Confirmation required",
            execution_id=str(confirmation.id),
        )

    response = await executor.execute(body, user_id, project_id)
    return response


@router.post("/workflows/execute")
async def execute_workflow(
    body: WorkflowRequest,
    auth: Annotated[ActionAuthContext, Depends(get_action_auth)],
    db: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    if auth.api_key and "write" not in set(auth.api_key.scopes or []) and "*" not in set(auth.api_key.scopes or []):
        raise HTTPException(status_code=403, detail="API key lacks write scope")
    project_id = auth.project_id or uuid.UUID(body.project_id)
    project = await require_project_membership(str(project_id), auth.user, db)
    if auth.project_id is not None and auth.project_id != project.id:
        raise HTTPException(status_code=403, detail="API key is not authorized for this project")
    uow = UnitOfWork(db)
    executor = ActionExecutor(uow)

    for step in body.steps:
        valid, error = GuardrailService.validate_action_arguments(
            step.provider, step.action, step.arguments
        )
        if not valid:
            raise HTTPException(status_code=400, detail=error)

    async def event_stream():
        async for event in executor.execute_workflow(body, auth.user.id):
            yield f"data: {event}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/executions", response_model=list[ActionExecutionRead])
async def list_executions(
    auth: Annotated[ActionAuthContext, Depends(get_action_auth)],
    project_id: Annotated[str | None, None] = None,
    db: AsyncSession = Depends(get_session),
) -> list[ActionExecutionRead]:
    stmt = select(ActionExecution).where(ActionExecution.user_id == auth.user.id)
    if project_id:
        await require_project_membership(project_id, auth.user, db)
        if auth.project_id and uuid.UUID(project_id) != auth.project_id:
            raise HTTPException(status_code=403, detail="API key is not authorized for this project")
        stmt = stmt.where(ActionExecution.project_id == uuid.UUID(project_id))
    elif auth.project_id:
        stmt = stmt.where(ActionExecution.project_id == auth.project_id)
    stmt = stmt.order_by(ActionExecution.created_at.desc()).limit(100)
    result = await db.execute(stmt)
    executions = result.scalars().all()
    return [
        ActionExecutionRead(
            id=str(e.id),
            user_id=str(e.user_id),
            project_id=str(e.project_id),
            provider=e.provider,
            action=e.action,
            arguments=e.arguments,
            result=e.result,
            error=e.error,
            status=e.status,
            duration_ms=e.duration_ms,
            tokens_used=e.tokens_used,
            cost=e.cost,
            created_at=e.created_at.isoformat(),
        )
        for e in executions
    ]


@router.post("/confirmations/{confirmation_id}/approve", response_model=ActionResponse)
async def approve_confirmation(
    confirmation_id: str,
    auth: Annotated[ActionAuthContext, Depends(get_action_auth)],
    db: AsyncSession = Depends(get_session),
) -> ActionResponse:
    if auth.api_key and "write" not in set(auth.api_key.scopes or []) and "*" not in set(auth.api_key.scopes or []):
        raise HTTPException(status_code=403, detail="API key lacks write scope")
    uow = UnitOfWork(db)
    service = ConfirmationService(uow)
    try:
        confirmation_id_uuid = uuid.UUID(confirmation_id)
        pending = await uow.action_confirmations.get(confirmation_id_uuid)
        if pending is None:
            raise ValueError("Confirmation not found")
        if pending.user_id != auth.user.id and not auth.user.is_superuser:
            raise HTTPException(status_code=404, detail="Confirmation not found")
        await require_project_membership(str(pending.project_id), auth.user, db)
        confirmation = await service.approve(confirmation_id_uuid)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    body = ActionRequest(
        project_id=str(confirmation.project_id),
        provider=confirmation.provider,
        action=confirmation.action,
        arguments=confirmation.arguments,
        confirm=True,
    )
    executor = ActionExecutor(uow)
    return await executor.execute(body, auth.user.id, confirmation.project_id)


@router.post("/confirmations/{confirmation_id}/reject", status_code=status.HTTP_204_NO_CONTENT)
async def reject_confirmation(
    confirmation_id: str,
    auth: Annotated[ActionAuthContext, Depends(get_action_auth)],
    db: AsyncSession = Depends(get_session),
) -> None:
    if auth.api_key and "write" not in set(auth.api_key.scopes or []) and "*" not in set(auth.api_key.scopes or []):
        raise HTTPException(status_code=403, detail="API key lacks write scope")
    uow = UnitOfWork(db)
    service = ConfirmationService(uow)
    try:
        confirmation_id_uuid = uuid.UUID(confirmation_id)
        pending = await uow.action_confirmations.get(confirmation_id_uuid)
        if pending is None:
            raise ValueError("Confirmation not found")
        if pending.user_id != auth.user.id and not auth.user.is_superuser:
            raise HTTPException(status_code=404, detail="Confirmation not found")
        await require_project_membership(str(pending.project_id), auth.user, db)
        confirmation = await service.reject(confirmation_id_uuid)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
