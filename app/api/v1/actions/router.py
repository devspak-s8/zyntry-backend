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
from app.models.actions import ActionConfirmation, ActionExecution
from app.models.users import User
from app.repositories import UnitOfWork
from app.schemas.actions import (
    ActionExecutionRead,
    ActionConfirmationRead,
    ActionRequest,
    ActionResponse,
    WorkflowRequest,
)
from app.services.actions.confirmations import ConfirmationService
from app.services.actions.executor import ActionExecutor
from app.services.actions.guardrails import GuardrailService, requires_action_confirmation

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

    from app.services.actions.registry import ActionRegistry

    try:
        provider_actions = ActionRegistry.list_actions(body.provider)
    except KeyError:
        provider_actions = []
    action_definition = next(
        (definition for definition in provider_actions if definition.name == body.action),
        None,
    )
    requires_confirmation = requires_action_confirmation(body.action)
    if action_definition is not None:
        # Provider metadata is the authoritative write/risk declaration. This
        # covers operations such as update_cells and send_messages whose names
        # do not contain a legacy risk keyword.
        requires_confirmation = requires_action_confirmation(body.action, action_definition)

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

    from app.services.actions.registry import ActionRegistry
    write_steps = []
    for step in body.steps:
        try:
            provider_actions = ActionRegistry.list_actions(step.provider)
        except KeyError:
            provider_actions = []
        definition = next(
            (
                item
                for item in provider_actions
                if item.name == step.action
            ),
            None,
        )
        if requires_action_confirmation(step.action, definition):
            write_steps.append(f"{step.provider}.{step.action}")
    if write_steps and not body.confirm:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "workflow_confirmation_required",
                "message": "This workflow contains write operations and requires explicit confirmation.",
                "actions": write_steps,
            },
        )

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


@router.get("/confirmations", response_model=list[ActionConfirmationRead])
async def list_confirmations(
    auth: Annotated[ActionAuthContext, Depends(get_action_auth)],
    project_id: Annotated[str | None, None] = None,
    status_filter: Annotated[str | None, None] = None,
    db: AsyncSession = Depends(get_session),
) -> list[ActionConfirmationRead]:
    """List pending and historical write approvals for the approval inbox."""
    stmt = select(ActionConfirmation).where(ActionConfirmation.user_id == auth.user.id)
    if project_id:
        await require_project_membership(project_id, auth.user, db)
        pid = uuid.UUID(project_id)
        if auth.project_id and pid != auth.project_id:
            raise HTTPException(status_code=403, detail="API key is not authorized for this project")
        stmt = stmt.where(ActionConfirmation.project_id == pid)
    elif auth.project_id:
        stmt = stmt.where(ActionConfirmation.project_id == auth.project_id)
    if status_filter:
        normalized_status = status_filter.strip().lower()
        if normalized_status not in {"pending", "running", "succeeded", "failed", "cancelled"}:
            raise HTTPException(status_code=400, detail="Invalid confirmation status")
        stmt = stmt.where(ActionConfirmation.status == normalized_status)
    stmt = stmt.order_by(ActionConfirmation.created_at.desc()).limit(100)
    result = await db.execute(stmt)
    confirmations = result.scalars().all()
    return [
        ActionConfirmationRead(
            id=str(item.id),
            user_id=str(item.user_id),
            project_id=str(item.project_id),
            provider=item.provider,
            action=item.action,
            arguments=item.arguments or {},
            risk=item.risk,
            status=item.status,
            expires_at=item.expires_at.isoformat(),
            created_at=item.created_at.isoformat(),
        )
        for item in confirmations
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
