from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.core.database import get_session
from app.models.users import User
from app.repositories import UnitOfWork
from app.schemas.integrations import IntegrationDefinitionRead
from app.services.integrations.service import IntegrationService

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.get("", response_model=list[IntegrationDefinitionRead])
async def list_integrations(
    current_user: Annotated[User, Depends(get_current_user)],
    category: Annotated[str | None, Query(description="Filter by category")] = None,
    db: AsyncSession = Depends(get_session),
) -> list[IntegrationDefinitionRead]:
    uow = UnitOfWork(db)
    service = IntegrationService(uow)
    return service.list_definitions(category=category)


@router.get("/{slug_or_id}", response_model=IntegrationDefinitionRead)
async def get_integration(
    slug_or_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> IntegrationDefinitionRead:
    uow = UnitOfWork(db)
    service = IntegrationService(uow)
    defn = service.get_definition(slug_or_id)
    if defn is None:
        raise HTTPException(status_code=404, detail=f"Integration '{slug_or_id}' not found")
    return defn
