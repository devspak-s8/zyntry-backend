from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.services.feature_flags import FeatureFlagService
from app.api.v1.dependencies import get_current_user
from app.core.database import get_session
from app.models.users import User


def require_feature(
    key: str,
) -> Callable[..., Coroutine[Any, Any, None]]:
    """FastAPI dependency that enforces a feature flag on the backend."""

    async def _require_feature(
        current_user: Annotated[User, Depends(get_current_user)],
        db: Annotated[AsyncSession, Depends(get_session)],
    ) -> None:
        if not await FeatureFlagService(db).is_enabled(key, current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Feature is not available for this account",
            )

    return _require_feature
