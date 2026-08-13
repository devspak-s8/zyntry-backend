from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app.models.actions import ActionAuditLog, ActionConfirmation, ActionExecution
from app.repositories import UnitOfWork
from app.services.runtime_assistant.permissions import check_tool_permission
from app.services.runtime_assistant.prompts import build_tool_definitions
from app.services.runtime_assistant.redaction import redact_sensitive
from app.services.runtime_assistant.schemas import ToolCall, UserRole
from app.services.runtime_assistant.tools import RuntimeAssistantTools


ALLOWED_COMMANDS = {
    "restart_runtime",
    "sync_sources",
    "rebuild_embeddings",
    "clear_cache",
    "pause_runtime",
    "resume_runtime",
    "test_provider",
    "test_tool",
    "run_health_check",
    "enable_dynamic_routing",
    "disable_dynamic_routing",
    "change_default_provider",
    "change_temperature",
    "change_max_tokens",
}


class RuntimeAssistantCommandService:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def propose(
        self,
        *,
        runtime_id: uuid.UUID,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
        user_role: UserRole,
        action: str,
        arguments: dict[str, Any],
    ) -> ActionConfirmation:
        if action not in ALLOWED_COMMANDS:
            raise ValueError("This command is not available to Runtime Assistant")
        tools = build_tool_definitions()
        decision = check_tool_permission(
            user_role, action, [tool.model_dump() for tool in tools]
        )
        safe_arguments = redact_sensitive(arguments)
        if not decision.allowed:
            await self._audit(
                runtime_id, project_id, user_id, action, safe_arguments,
                "permission_denied", decision.reason
            )
            raise PermissionError(decision.reason or "Permission denied")
        proposal = ActionConfirmation(
            user_id=user_id,
            project_id=project_id,
            provider="runtime_assistant",
            action=action,
            arguments={"runtime_id": str(runtime_id), **safe_arguments},
            risk="high" if action in {"restart_runtime", "pause_runtime", "clear_cache"} else "medium",
            status="pending",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        )
        self.uow.session.add(proposal)
        await self.uow.commit()
        return proposal

    async def resolve(
        self,
        *,
        proposal_id: uuid.UUID,
        runtime_id: uuid.UUID,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
        user_role: UserRole,
        confirm: bool,
    ) -> dict[str, Any]:
        proposal = await self.uow.action_confirmations.get(proposal_id)
        if (
            proposal is None
            or proposal.project_id != project_id
            or proposal.user_id != user_id
            or proposal.arguments.get("runtime_id") != str(runtime_id)
        ):
            raise ValueError("Action proposal not found in this runtime scope")
        if proposal.status != "pending":
            raise ValueError("Action proposal is no longer pending")
        if proposal.expires_at <= datetime.now(timezone.utc):
            proposal.status = "expired"
            await self.uow.commit()
            raise ValueError("Action proposal expired")
        if not confirm:
            proposal.status = "cancelled"
            await self._audit(runtime_id, project_id, user_id, proposal.action, proposal.arguments, "cancelled")
            await self.uow.commit()
            return {"status": "cancelled", "proposal_id": str(proposal.id)}

        tools = build_tool_definitions()
        decision = check_tool_permission(
            user_role, proposal.action, [tool.model_dump() for tool in tools]
        )
        if not decision.allowed:
            proposal.status = "permission_denied"
            await self._audit(runtime_id, project_id, user_id, proposal.action, proposal.arguments, "permission_denied", decision.reason)
            await self.uow.commit()
            raise PermissionError(decision.reason or "Permission denied")

        proposal.status = "confirmed"
        execution = ActionExecution(
            user_id=user_id,
            project_id=project_id,
            provider="runtime_assistant",
            action=proposal.action,
            arguments=redact_sensitive(proposal.arguments),
            status="running",
        )
        self.uow.session.add(execution)
        await self.uow.session.flush()
        client = RuntimeAssistantTools(
            self.uow, str(runtime_id), str(user_id), user_role, str(project_id)
        )
        call = await client.execute(
            ToolCall(
                id=str(uuid.uuid4()),
                name=proposal.action,
                arguments={k: v for k, v in proposal.arguments.items() if k != "runtime_id"},
            )
        )
        execution.status = "succeeded" if call.status == "success" else "failed"
        execution.result = redact_sensitive(call.result)
        execution.error = redact_sensitive(call.error)
        execution.duration_ms = round(call.duration_ms or 0)
        proposal.status = "executed" if call.status == "success" else "failed"
        await self._audit(runtime_id, project_id, user_id, proposal.action, proposal.arguments, execution.status, execution.error, execution.result, execution.duration_ms)
        await self.uow.commit()
        return {
            "status": execution.status,
            "proposal_id": str(proposal.id),
            "execution_id": str(execution.id),
            "result": execution.result,
            "error": execution.error,
        }

    async def _audit(
        self, runtime_id: uuid.UUID, project_id: uuid.UUID, user_id: uuid.UUID,
        action: str, arguments: dict[str, Any], status: str,
        error: str | None = None, result: Any = None, duration_ms: int | None = None,
    ) -> None:
        self.uow.session.add(
            ActionAuditLog(
                user_id=user_id,
                project_id=project_id,
                provider="runtime_assistant",
                action=action,
                arguments=redact_sensitive({"runtime_id": str(runtime_id), **arguments}),
                result=redact_sensitive(result),
                status=status,
                duration_ms=duration_ms,
                error=redact_sensitive(error),
            )
        )
        await self.uow.session.flush()
