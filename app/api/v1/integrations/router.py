from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.core.database import get_session
from app.models.users import User
from app.repositories import UnitOfWork
from app.schemas.integrations import IntegrationCatalogResponse, IntegrationDefinitionRead
from app.services.integrations.service import IntegrationService

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.get("", response_model=IntegrationCatalogResponse)
async def list_integrations(
    current_user: Annotated[User, Depends(get_current_user)],
    category: Annotated[str | None, Query(description="Filter by category (developer, communication, productivity, google, databases, storage, web_documents, geospatial, ai_providers)")] = None,
    status: Annotated[str | None, Query(description="Filter by availability status (available, beta, coming_soon, disabled, deprecated)")] = None,
    search: Annotated[str | None, Query(description="Search by name, slug, or description")] = None,
    db: AsyncSession = Depends(get_session),
) -> IntegrationCatalogResponse:
    """Return the currently supported integration catalog with capabilities, auth methods, and status."""
    uow = UnitOfWork(db)
    service = IntegrationService(uow)
    integrations = service.list_definitions(category=category, status=status, search=search)
    return IntegrationCatalogResponse(integrations=integrations, total=len(integrations))


@router.get("/{slug_or_id}", response_model=IntegrationDefinitionRead)
async def get_integration(
    slug_or_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> IntegrationDefinitionRead:
    """Return the complete definition and capability set for a single integration."""
    uow = UnitOfWork(db)
    service = IntegrationService(uow)
    defn = service.get_definition(slug_or_id)
    if defn is None:
        raise HTTPException(status_code=404, detail=f"Integration '{slug_or_id}' not found")
    return defn
