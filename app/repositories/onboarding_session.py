from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.onboarding_session import OnboardingSession


class OnboardingSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, id: UUID) -> OnboardingSession | None:
        return await self.session.get(OnboardingSession, id)

    async def get_latest_active_by_user(self, user_id: UUID) -> OnboardingSession | None:
        result = await self.session.execute(
            select(OnboardingSession)
            .where(OnboardingSession.user_id == user_id)
            .where(OnboardingSession.state != "completed")
            .order_by(OnboardingSession.created_at.desc())
        )
        return result.scalars().first()

    async def create(self, **kwargs: object) -> OnboardingSession:
        session = OnboardingSession(**kwargs)
        self.session.add(session)
        await self.session.flush()
        return session

    async def update(self, instance: OnboardingSession, **kwargs: object) -> OnboardingSession:
        for key, value in kwargs.items():
            setattr(instance, key, value)
        await self.session.flush()
        return instance
