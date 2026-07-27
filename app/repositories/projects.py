from __future__ import annotations

from app.models.projects import Project
from app.repositories.base import BaseRepository


class ProjectRepository(BaseRepository[Project]):
    model = Project
