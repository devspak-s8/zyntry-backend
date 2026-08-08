from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from app.models.actions import ActionAuditLog
from app.repositories import UnitOfWork


class AuditService:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def log(self, user_id: uuid.UUID, project_id: uuid.UUID, provider: str, action: str, arguments: dict[str, Any], result: Any, status: str, duration_ms: int, error: str | None = None, tokens_used: int = 0, cost: float = 0.0) -> ActionAuditLog:
        log_entry = ActionAuditLog(
            user_id=user_id,
            project_id=project_id,
            provider=provider,
            action=action,
            arguments=arguments,
            result=result,
            status=status,
            duration_ms=duration_ms,
            error=error,
            tokens_used=tokens_used,
            cost=cost,
            created_at=datetime.now(UTC),
        )
        self.uow.action_audit_logs.create(
            user_id=user_id,
            project_id=project_id,
            provider=provider,
            action=action,
            arguments=arguments,
            result=result,
            status=status,
            duration_ms=duration_ms,
            error=error,
            tokens_used=tokens_used,
            cost=cost,
        )
        await self.uow.commit()
        return log_entry
