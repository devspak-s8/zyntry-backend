from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.security import hash_token
from app.models.apikeys import ApiKey
from app.models.users import User


async def get_api_key_user(
    authorization: str | None = None,
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

    if api_key.expires_at and api_key.expires_at <= __import__("datetime").datetime.now(__import__("datetime").timezone.utc):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key expired")

    user = await db.get(User, api_key.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    api_key.usage_count = (api_key.usage_count or 0) + 1
    await db.commit()

    return user
