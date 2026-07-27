from __future__ import annotations

from datetime import datetime
from typing import Any

from app.repositories import UnitOfWork
from app.schemas.onboarding import OnboardingStateCreate, OnboardingStateUpdate


class OnboardingService:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def get_or_create(self, data: OnboardingStateCreate) -> dict:
        existing = None
        if data.project_id:
            existing = await self.uow.onboarding.get_by_project(data.project_id)
        elif data.organization_id:
            existing = await self.uow.onboarding.get_by_org(data.organization_id)

        if existing:
            return {
                "id": str(existing.id),
                "current_step": existing.current_step,
                "completed_steps": existing.completed_steps,
                "extra_data": existing.extra_data,
            }

        created = await self.uow.onboarding.create(
            organization_id=data.organization_id,
            project_id=data.project_id,
            current_step=data.current_step,
            completed_steps=data.completed_steps,
            extra_data=data.extra_data,
        )
        await self.uow.commit()
        return {
            "id": str(created.id),
            "current_step": created.current_step,
            "completed_steps": created.completed_steps,
            "extra_data": created.extra_data,
        }

    async def update(self, state_id: str, data: OnboardingStateUpdate) -> dict:
        existing = await self.uow.onboarding.session.get(
            self.uow.onboarding.__class__, state_id
        )
        if not existing:
            raise ValueError("Onboarding state not found")

        update_data = data.model_dump(exclude_unset=True)
        updated = await self.uow.onboarding.update(existing, **update_data)
        await self.uow.commit()
        result = {
            "id": str(updated.id),
            "current_step": updated.current_step,
            "completed_steps": updated.completed_steps,
            "extra_data": updated.extra_data,
        }
        if updated.project_id and updated.current_step == "complete":
            await self._maybe_trigger_runtime(str(updated.project_id))
        return result

    async def _maybe_trigger_runtime(self, project_id: str) -> None:
        from app.services.runtimes import RuntimeService
        service = RuntimeService(self.uow)
        runtime = await service.get_by_project(project_id)
        if runtime and runtime.get("status") in ("queued", "failed", "cancelled"):
            await service.enqueue_build(runtime["id"], trigger="onboarding_complete")
