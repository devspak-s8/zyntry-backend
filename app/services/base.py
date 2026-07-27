from __future__ import annotations

from app.core.database import AsyncSession
from app.repositories import UnitOfWork


class BaseService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.uow = UnitOfWork(session)
