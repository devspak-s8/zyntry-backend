from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import _get_session_user
from app.core.database import get_session
from app.core.security import hash_token
from app.models.apikeys import ApiKey
from app.models.users import User


@dataclass
class ActionAuthContext:
    user: User
    project_id: uuid.UUID | None = None
    api_key: ApiKey | None = None


async def get_api_key_user(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    db: AsyncSession = Depends(get_session),
) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    raw_key = authorization[7:]
    if not raw_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    token_hash = hash_token(raw_key)
    result = await db.execute(select(ApiKey).where(ApiKey.hashed_key == token_hash))
    api_key = result.scalar_one_or_none()
    if api_key is None or api_key.revoked:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    if api_key.expires_at and api_key.expires_at <= datetime.now(UTC):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key expired")

    user = await db.get(User, api_key.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    if api_key.organization_id is not None and api_key.organization_id != user.organization_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    api_key.usage_count = (api_key.usage_count or 0) + 1
    request.state.api_key_id = api_key.id
    request.state.api_key_project_id = api_key.project_id
    await db.commit()
    return user


async def get_action_auth(
    session_token: Annotated[str | None, Cookie(alias="zyntra_session")] = None,
    authorization: Annotated[str | None, Header()] = None,
    db: AsyncSession = Depends(get_session),
) -> ActionAuthContext:
    if session_token:
        user = await _get_session_user(session_token, db)
        if user:
            return ActionAuthContext(user=user)

    if authorization and authorization.startswith("Bearer "):
        raw_key = authorization[7:]
        if raw_key:
            token_hash = hash_token(raw_key)
            result = await db.execute(select(ApiKey).where(ApiKey.hashed_key == token_hash))
            api_key = result.scalar_one_or_none()
            if (
                api_key
                and not api_key.revoked
                and (not api_key.expires_at or api_key.expires_at > datetime.now(UTC))
            ):
                user = await db.get(User, api_key.user_id)
                if (
                    user
                    and user.is_active
                    and (
                        api_key.organization_id is None
                        or api_key.organization_id == user.organization_id
                    )
                ):
                    api_key.usage_count = (api_key.usage_count or 0) + 1
                    await db.commit()
                    return ActionAuthContext(
                        user=user,
                        project_id=api_key.project_id,
                        api_key=api_key,
                    )

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
