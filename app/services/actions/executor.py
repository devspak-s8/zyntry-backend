from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.models.actions import ActionExecution, ActionStatus
from app.repositories import UnitOfWork
from app.schemas.actions import ActionRequest, ActionResponse
from app.services.actions.registry import ActionRegistry


class ActionExecutor:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def execute(self, body: ActionRequest, user_id: uuid.UUID, project_id: uuid.UUID) -> ActionResponse:
        execution = ActionExecution(
            user_id=user_id,
            project_id=project_id,
            provider=body.provider,
            action=body.action,
            arguments=body.arguments,
            status=ActionStatus.RUNNING,
            created_at=datetime.now(UTC),
        )
        self.uow.actions.create(
            user_id=execution.user_id,
            project_id=execution.project_id,
            provider=execution.provider,
            action=execution.action,
            arguments=execution.arguments,
            status=execution.status,
        )
        await self.uow.commit()

        start = datetime.now(UTC)
        try:
            result = await ActionRegistry.execute(body.provider, body.action, body.arguments, {"user_id": str(user_id), "project_id": str(project_id)})
            execution.status = ActionStatus.SUCCEEDED
            execution.result = result
            execution.duration_ms = int((datetime.now(UTC) - start).total_seconds() * 1000)
            await self.uow.actions.update(execution, status=ActionStatus.SUCCEEDED, result=result, duration_ms=execution.duration_ms)
            await self.uow.commit()
            return ActionResponse(success=True, result=result, execution_id=str(execution.id))
        except Exception as exc:
            execution.status = ActionStatus.FAILED
            execution.error = str(exc)
            execution.duration_ms = int((datetime.now(UTC) - start).total_seconds() * 1000)
            await self.uow.actions.update(execution, status=ActionStatus.FAILED, error=str(exc), duration_ms=execution.duration_ms)
            await self.uow.commit()
            return ActionResponse(success=False, error=str(exc), execution_id=str(execution.id))
