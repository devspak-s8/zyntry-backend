from __future__ import annotations

from app.models.actions import ActionAuditLog, ActionConfirmation, ActionExecution
from app.repositories.base import BaseRepository


class ActionExecutionRepository(BaseRepository[ActionExecution]):
    model = ActionExecution


class ActionConfirmationRepository(BaseRepository[ActionConfirmation]):
    model = ActionConfirmation


class ActionAuditLogRepository(BaseRepository[ActionAuditLog]):
    model = ActionAuditLog
