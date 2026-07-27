from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.onboarding import OnboardingState


class OnboardingStateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_project(self, project_id: UUID) -> OnboardingState | None:
        result = await self.session.execute(
            select(OnboardingState).where(OnboardingState.project_id == project_id)
        )
        return result.scalar_one_or_none()

    async def get_by_org(self, organization_id: UUID) -> OnboardingState | None:
        result = await self.session.execute(
            select(OnboardingState).where(OnboardingState.organization_id == organization_id)
        )
        return result.scalar_one_or_none()

    async def create(self, **kwargs: object) -> OnboardingState:
        state = OnboardingState(**kwargs)
        self.session.add(state)
        await self.session.flush()
        return state

    async def update(self, instance: OnboardingState, **kwargs: object) -> OnboardingState:
        for key, value in kwargs.items():
            setattr(instance, key, value)
        await self.session.flush()
        return instance
