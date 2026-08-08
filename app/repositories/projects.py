from __future__ import annotations

from sqlalchemy import select

from app.models.projects import Project
from app.repositories.base import BaseRepository


class ProjectRepository(BaseRepository[Project]):
    model = Project

    async def get_by_organization(self, organization_id: str) -> Project | None:
        result = await self.session.execute(
            select(Project).where(Project.organization_id == organization_id).limit(1)
        )
        return result.scalar_one_or_none()
