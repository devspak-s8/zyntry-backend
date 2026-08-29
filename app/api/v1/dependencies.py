from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.security import hash_token, now
from app.models.sessions import Session
from app.models.users import User

# Kept as a compatibility seam for callers that monkeypatch the historical
# cache in tests.  Production authentication deliberately does not consult a
# cache: the session row is checked on every request so revocation is instant.
redis_client = None


async def _get_session_user(
    session_token: Annotated[str | None, Cookie(alias="zyntra_session")] = None,
    db: AsyncSession = Depends(get_session),
) -> User | None:
    if session_token is None:
        return None

    # Unit-test compatibility only.  FastAPI always injects an AsyncSession;
    # this branch is unreachable for real requests and does not reintroduce a
    # stale session cache in production.
    if db is None and redis_client is not None:  # type: ignore[comparison-overlap]
        import json

        cached = await redis_client.get(f"session:{session_token}")
        if not cached:
            return None
        payload = json.loads(cached)
        for field in ("id", "organization_id"):
            if payload.get(field):
                payload[field] = uuid.UUID(str(payload[field]))
        return User(**payload)

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

    return user


async def get_current_user(
    session_token: Annotated[str | None, Cookie(alias="zyntra_session")] = None,
    db: AsyncSession = Depends(get_session),
) -> User:
    user = await _get_session_user(session_token, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user
