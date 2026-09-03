from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from app.models.actions import ActionExecution, ActionStatus
from app.repositories import UnitOfWork
from app.schemas.actions import ActionRequest, ActionResponse, WorkflowRequest
from app.services.actions.registry import ActionRegistry
from app.services.oauth.service import OAuthService


class ActionExecutor:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def execute(
        self,
        body: ActionRequest,
        user_id: uuid.UUID,
        project_id: uuid.UUID,
    ) -> ActionResponse:
        execution = ActionExecution(
            user_id=user_id,
            project_id=project_id,
            provider=body.provider,
            action=body.action,
            arguments=body.arguments,
            status=ActionStatus.RUNNING,
            created_at=datetime.now(UTC),
        )
        await self.uow.actions.create(
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
            result = await ActionRegistry.execute(
                body.provider,
                body.action,
                body.arguments,
                {
                    "user_id": str(user_id),
                    "project_id": str(project_id),
                    "confirmed": body.confirm,
                },
                uow=self.uow,
            )
            execution.status = ActionStatus.SUCCEEDED
            execution.result = result
            duration_ms = int((datetime.now(UTC) - start).total_seconds() * 1000)
            execution.duration_ms = duration_ms
            await self.uow.actions.update(
                execution,
                status=ActionStatus.SUCCEEDED,
                result=result,
                duration_ms=duration_ms,
            )
            await self.uow.commit()
            return ActionResponse(
                success=True,
                result=result,
                execution_id=str(execution.id),
            )
        except Exception as exc:
            execution.status = ActionStatus.FAILED
            execution.error = str(exc)
            duration_ms = int((datetime.now(UTC) - start).total_seconds() * 1000)
            execution.duration_ms = duration_ms
            await self.uow.actions.update(
                execution,
                status=ActionStatus.FAILED,
                error=str(exc),
                duration_ms=duration_ms,
            )
            await self.uow.commit()
            return ActionResponse(
                success=False,
                error=str(exc),
                execution_id=str(execution.id),
            )

    async def execute_workflow(
        self,
        body: WorkflowRequest,
        user_id: uuid.UUID,
    ) -> AsyncIterator[dict[str, Any]]:
        context = dict(body.context)
        context["user_id"] = str(user_id)
        context["project_id"] = body.project_id
        context["confirmed"] = body.confirm

        providers_needed = {step.provider for step in body.steps}
        if providers_needed and self.uow:
            try:
                oauth_service = OAuthService(self.uow)
                project_uuid = uuid.UUID(body.project_id) if body.project_id else None
                if project_uuid:
                    resolved = await oauth_service.pre_resolve_project_tokens(project_uuid)
                    context["_resolved_oauth_tokens"] = resolved
            except Exception:
                pass

        for step in body.steps:
            now_ts = datetime.now(UTC).isoformat()
            yield {
                "type": "step_start",
                "step": step.model_dump(),
                "timestamp": now_ts,
            }

            if step.depends_on:
                dep_result = context.get(step.depends_on)
                if dep_result is None:
                    now_ts = datetime.now(UTC).isoformat()
                    yield {
                        "type": "step_error",
                        "step": step.model_dump(),
                        "error": f"Dependency '{step.depends_on}' not found",
                        "timestamp": now_ts,
                    }
                    continue

            if step.condition and not context.get(step.condition):
                now_ts = datetime.now(UTC).isoformat()
                yield {
                    "type": "step_skipped",
                    "step": step.model_dump(),
                    "reason": f"Condition '{step.condition}' not met",
                    "timestamp": now_ts,
                }
                continue

            try:
                from app.services.actions.guardrails import requires_action_confirmation
                from app.services.actions.registry import ActionRegistry

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
                if requires_action_confirmation(step.action, definition) and not body.confirm:
                    yield {
                        "type": "step_error",
                        "step": step.model_dump(),
                        "error": "Workflow write operation requires explicit confirmation",
                        "timestamp": now_ts,
                    }
                    break
                result = await ActionRegistry.execute(
                    step.provider,
                    step.action,
                    step.arguments,
                    context,
                    uow=self.uow,
                )
                context[step.action] = result
                now_ts = datetime.now(UTC).isoformat()
                yield {
                    "type": "step_complete",
                    "step": step.model_dump(),
                    "result": result,
                    "timestamp": now_ts,
                }
            except Exception as exc:
                now_ts = datetime.now(UTC).isoformat()
                yield {
                    "type": "step_error",
                    "step": step.model_dump(),
                    "error": str(exc),
                    "timestamp": now_ts,
                }
                break

        yield {"type": "workflow_complete", "timestamp": datetime.now(UTC).isoformat()}
