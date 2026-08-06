from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.core.database import get_session
from app.models.actions import ActionExecution
from app.models.users import User
from app.repositories import UnitOfWork
from app.schemas.actions import (
    ActionExecutionRead,
    ActionRequest,
    ActionResponse,
)
from app.services.actions.confirmations import ConfirmationService
from app.services.actions.executor import ActionExecutor

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
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> ActionResponse:
    uow = UnitOfWork(db)
    executor = ActionExecutor(uow)

    risk_actions = {"delete", "remove", "archive", "merge", "close", "cancel", "expire", "revoke"}
    requires_confirmation = any(risk in body.action.lower() for risk in risk_actions)

    if requires_confirmation and not body.confirm:
        confirmation_service = ConfirmationService(uow)
        project_id = current_user.organization_id or uuid.uuid4()
        confirmation = await confirmation_service.request(
            user_id=current_user.id,
            project_id=project_id,
            provider=body.provider,
            action=body.action,
            arguments=body.arguments,
            risk="high" if any(d in body.action.lower() for d in ["delete", "remove", "archive"]) else "medium",
        )
        return ActionResponse(
            success=False,
            error="Confirmation required",
            execution_id=str(confirmation.id),
        )

    project_id = current_user.organization_id or uuid.uuid4()
    response = await executor.execute(body, current_user.id, project_id)

    if response.success:
        from app.services.actions.audit import AuditService
        audit = AuditService(uow)
        await audit.log(
            user_id=current_user.id,
            project_id=project_id,
            provider=body.provider,
            action=body.action,
            arguments=body.arguments,
            result=response.result,
            status="success",
            duration_ms=0,
            tokens_used=0,
            cost=0.0,
        )
    return response


@router.get("/executions", response_model=list[ActionExecutionRead])
async def list_executions(
    current_user: Annotated[User, Depends(get_current_user)],
    project_id: Annotated[str | None, None] = None,
    db: AsyncSession = Depends(get_session),
) -> list[ActionExecutionRead]:
    uow = UnitOfWork(db)
    stmt = select(ActionExecution).where(ActionExecution.user_id == current_user.id)
    if project_id:
        stmt = stmt.where(ActionExecution.project_id == uuid.UUID(project_id))
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
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> ActionResponse:
    uow = UnitOfWork(db)
    service = ConfirmationService(uow)
    try:
        confirmation = await service.approve(uuid.UUID(confirmation_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    body = ActionRequest(
        provider=confirmation.provider,
        action=confirmation.action,
        arguments=confirmation.arguments,
        confirm=True,
    )
    executor = ActionExecutor(uow)
    project_id = confirmation.project_id
    return await executor.execute(body, current_user.id, project_id)


@router.post("/confirmations/{confirmation_id}/reject", status_code=status.HTTP_204_NO_CONTENT)
async def reject_confirmation(
    confirmation_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> None:
    uow = UnitOfWork(db)
    service = ConfirmationService(uow)
    try:
        await service.reject(uuid.UUID(confirmation_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
