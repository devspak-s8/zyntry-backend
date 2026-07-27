from __future__ import annotations

from typing import Any, Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    model: type[ModelType]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **kwargs: Any) -> ModelType:
        instance = self.model(**kwargs)
        self.session.add(instance)
        await self.session.flush()
        return instance

    async def get(self, id: Any) -> ModelType | None:
        result = await self.session.get(self.model, id)
        return result

    async def list(self, limit: int = 20, offset: int = 0) -> list[ModelType]:
        stmt = select(self.model).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update(self, instance: ModelType, **kwargs: Any) -> ModelType:
        for key, value in kwargs.items():
            setattr(instance, key, value)
        await self.session.flush()
        return instance

    async def delete(self, instance: ModelType) -> None:
        await self.session.delete(instance)
        await self.session.flush()
