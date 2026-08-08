from __future__ import annotations

import json
import uuid
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.redis import redis_client
from app.core.security import hash_token, now
from app.models.sessions import Session
from app.models.users import User


async def _get_session_user(
    session_token: Annotated[str | None, Cookie(alias="zyntra_session")] = None,
    db: AsyncSession = Depends(get_session),
) -> User | None:
    if session_token is None:
        return None

    cache_key = f"session:{session_token}"
    cached = await redis_client.get(cache_key)
    if cached:
        data = json.loads(cached)
        return User(
            id=uuid.UUID(data["id"]),
            organization_id=(
                uuid.UUID(data["organization_id"]) if data.get("organization_id") else None
            ),
            email=data["email"],
            name=data.get("name"),
            is_active=data.get("is_active", True),
            is_superuser=data.get("is_superuser", False),
            email_verified=data.get("email_verified", False),
        )

    token_hash = hash_token(session_token)
    result = await db.execute(select(Session).where(Session.token_hash == token_hash))
    session_obj = result.scalar_one_or_none()

    if session_obj is None or session_obj.revoked:
        return None

    if session_obj.expires_at <= now():
        return None

    user = await db.get(User, session_obj.user_id)
    if user is None or not user.is_active:
        return None

    await redis_client.set(
        cache_key,
        json.dumps(
            {
                "id": str(user.id),
                "organization_id": (str(user.organization_id) if user.organization_id else None),
                "email": user.email,
                "name": user.name,
                "is_active": user.is_active,
                "is_superuser": user.is_superuser,
                "email_verified": user.email_verified,
            }
        ),
        ex=45,
    )

    return user


async def get_current_user(
    session_token: Annotated[str | None, Cookie(alias="zyntra_session")] = None,
    db: AsyncSession = Depends(get_session),
) -> User:
    user = await _get_session_user(session_token, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user
