from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from app.models.actions import ActionConfirmation, ActionStatus
from app.repositories import UnitOfWork


class ConfirmationService:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def request(
        self,
        user_id: uuid.UUID,
        project_id: uuid.UUID,
        provider: str,
        action: str,
        arguments: dict[str, Any],
        risk: str,
    ) -> ActionConfirmation:
        confirmation = await self.uow.action_confirmations.create(
            user_id=user_id,
            project_id=project_id,
            provider=provider,
            action=action,
            arguments=arguments,
            risk=risk,
            status=ActionStatus.PENDING,
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
            created_at=datetime.now(UTC),
        )
        await self.uow.commit()
        return confirmation

    async def approve(self, confirmation_id: uuid.UUID) -> ActionConfirmation:
        confirmation = await self.uow.action_confirmations.get(confirmation_id)
        if confirmation is None:
            raise ValueError("Confirmation not found")
        if confirmation.status != ActionStatus.PENDING:
            raise ValueError("Confirmation already resolved")
        if confirmation.expires_at <= datetime.now(UTC):
            await self.uow.action_confirmations.update(confirmation, status=ActionStatus.CANCELLED)
            await self.uow.commit()
            raise ValueError("Confirmation expired")
        await self.uow.action_confirmations.update(confirmation, status=ActionStatus.SUCCEEDED)
        await self.uow.commit()
        return confirmation

    async def reject(self, confirmation_id: uuid.UUID) -> ActionConfirmation:
        confirmation = await self.uow.action_confirmations.get(confirmation_id)
        if confirmation is None:
            raise ValueError("Confirmation not found")
        if confirmation.status != ActionStatus.PENDING:
            raise ValueError("Confirmation already resolved")
        if confirmation.expires_at <= datetime.now(UTC):
            await self.uow.action_confirmations.update(confirmation, status=ActionStatus.CANCELLED)
            await self.uow.commit()
            raise ValueError("Confirmation expired")
        await self.uow.action_confirmations.update(confirmation, status=ActionStatus.FAILED)
        await self.uow.commit()
        return confirmation
