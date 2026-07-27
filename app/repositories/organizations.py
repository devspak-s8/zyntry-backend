from __future__ import annotations

from app.models.organizations import Organization
from app.repositories.base import BaseRepository


class OrganizationRepository(BaseRepository[Organization]):
    model = Organization
