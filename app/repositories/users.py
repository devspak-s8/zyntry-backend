from __future__ import annotations

from app.models.users import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User
