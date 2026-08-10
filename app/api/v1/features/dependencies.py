from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.services.feature_flags import FeatureFlagService
from app.api.v1.dependencies import get_current_user
from app.api.v1.dependencies_api_key import (
    ActionAuthContext,
    get_action_auth,
    get_api_key_user,
)
from app.core.database import get_session
from app.models.users import User


def require_feature(
    key: str,
) -> Callable[..., Coroutine[Any, Any, User]]:
    """FastAPI dependency that enforces a feature flag on the backend."""

    async def _require_feature(
        current_user: Annotated[User, Depends(get_current_user)],
        db: Annotated[AsyncSession, Depends(get_session)],
    ) -> User:
        await _enforce_feature(key, current_user, db)
        return current_user

    return _require_feature


async def _enforce_feature(key: str, user: User, db: AsyncSession) -> None:
    if not await FeatureFlagService(db).is_enabled(key, user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Feature is not available for this account",
        )


def require_api_key_feature(
    key: str,
) -> Callable[..., Coroutine[Any, Any, User]]:
    """Authenticate an API key and enforce a feature for its owning user."""

    async def _require_api_key_feature(
        current_user: Annotated[User, Depends(get_api_key_user)],
        db: Annotated[AsyncSession, Depends(get_session)],
    ) -> User:
        await _enforce_feature(key, current_user, db)
        return current_user

    return _require_api_key_feature


def require_action_feature(
    key: str,
) -> Callable[..., Coroutine[Any, Any, ActionAuthContext]]:
    """Enforce a feature for action routes using session or API-key auth."""

    async def _require_action_feature(
        auth: Annotated[ActionAuthContext, Depends(get_action_auth)],
        db: Annotated[AsyncSession, Depends(get_session)],
    ) -> ActionAuthContext:
        await _enforce_feature(key, auth.user, db)
        return auth

    return _require_action_feature
