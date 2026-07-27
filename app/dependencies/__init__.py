from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from app.core.database import AsyncSession, get_session


async def get_db() -> AsyncSession:
    async for session in get_session():
        yield session


DbSession = Annotated[AsyncSession, Depends(get_db)]
