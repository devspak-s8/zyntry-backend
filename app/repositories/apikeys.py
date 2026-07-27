from __future__ import annotations

from app.models.apikeys import ApiKey
from app.repositories.base import BaseRepository


class ApiKeyRepository(BaseRepository[ApiKey]):
    model = ApiKey
