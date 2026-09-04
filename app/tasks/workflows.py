from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.workers.celery_app import celery_app
from app.core.database import run_async


@celery_app.task(name="app.tasks.workflows.run")
def run_workflow(workflow_id: str, input_data: dict | None = None) -> dict:
    """Execute a scheduled workflow with write actions held for approval."""
    async def _run() -> dict:
        from sqlalchemy import select

        from app.core.database import get_session
        from app.models.projects import Project
        from app.models.users import User
        from app.services.actions.guardrails import requires_action_confirmation
        from app.services.actions.registry import ActionRegistry
        from app.services.actions.confirmations import ConfirmationService
        from app.repositories import UnitOfWork

        async for session in get_session():
            uow = UnitOfWork(session)
            workflow = await uow.workflows.get(uuid.UUID(workflow_id))
            if workflow is None:
                return {"workflow_id": workflow_id, "status": "not_found"}
            project = await session.get(Project, workflow.project_id)
            if project is None:
                return {"workflow_id": workflow_id, "status": "project_not_found"}
            metadata = (workflow.definition or {}).get("_zyntry_metadata") or {}
            actor = None
            if metadata.get("created_by"):
                try:
                    actor = await session.get(User, uuid.UUID(str(metadata["created_by"])))
                except (TypeError, ValueError):
                    actor = None
            if actor is None:
                actor = await session.scalar(
                    select(User).where(User.organization_id == project.organization_id).order_by(User.created_at.asc())
                )
            if actor is None:
                return {"workflow_id": workflow_id, "status": "no_project_actor"}
            execution = await uow.workflow_executions.create(
                workflow_id=workflow.id,
                project_id=workflow.project_id,
                status="running",
                input_data=input_data or {},
            )
            await uow.commit()
            started = datetime.now(UTC)
            context = dict(input_data or {})
            completed = 0
            blocked: list[str] = []
            confirmation_ids: list[str] = []
            try:
                for step in (workflow.definition or {}).get("sequence", []):
                    provider, action = step.get("provider"), step.get("action")
                    if not provider or not action:
                        completed += 1
                        continue
                    try:
                        definition = next((item for item in ActionRegistry.list_actions(provider) if item.name == action), None)
                    except KeyError:
                        definition = None
                    if requires_action_confirmation(action, definition):
                        blocked.append(f"{provider}.{action}")
                        confirmation = await ConfirmationService(uow).request(
                            user_id=actor.id,
                            project_id=workflow.project_id,
                            provider=provider,
                            action=action,
                            arguments=step.get("arguments") or {},
                            risk="high" if any(item in action.lower() for item in ("delete", "remove", "archive")) else "medium",
                        )
                        confirmation_ids.append(str(confirmation.id))
                        continue
                    result = await ActionRegistry.execute(
                        provider,
                        action,
                        step.get("arguments") or {},
                        {"user_id": str(actor.id), "project_id": str(workflow.project_id), "confirmed": False},
                        uow=uow,
                    )
                    context[action] = result
                    completed += 1
                execution.status = "completed" if not blocked else "blocked"
                execution.output_data = {"steps_completed": completed, "blocked_actions": blocked, "confirmation_ids": confirmation_ids, "context": context}
            except Exception as exc:
                execution.status = "failed"
                execution.error_message = str(exc)
            execution.duration_ms = int((datetime.now(UTC) - started).total_seconds() * 1000)
            await uow.commit()
            return {
                "workflow_id": workflow_id,
                "execution_id": str(execution.id),
                "status": execution.status,
                "steps_completed": completed,
                "blocked_actions": blocked,
                "confirmation_ids": confirmation_ids,
            }

    return run_async(_run())
