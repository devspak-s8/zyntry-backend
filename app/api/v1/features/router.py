from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.services.feature_flags import FeatureFlagService
from app.api.v1.dependencies import get_current_user
from app.core.database import get_session
from app.models.users import User

router = APIRouter(prefix="/features", tags=["features"])


@router.get("/me", response_model=dict[str, bool])
async def get_my_features(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, bool]:
    """Return evaluated flags only; internal targeting configuration stays private."""
    return await FeatureFlagService(db).evaluate_all(current_user)
