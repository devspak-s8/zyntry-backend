from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.models.organizations import Organization
from app.models.projects import Project
from app.models.users import User


async def _get_current_user(
    session_token: Annotated[str | None, Header(alias="Authorization")] = None,
    db: AsyncSession = Depends(get_session),
) -> User | None:
    if not session_token or not session_token.startswith("Bearer "):
        return None
    from app.core.security import hash_token
    from app.models.sessions import Session

    token_hash = hash_token(session_token[7:])
    result = await db.execute(select(Session).where(Session.token_hash == token_hash))
    session_obj = result.scalar_one_or_none()
    from app.core.security import now

    if (
        session_obj is None
        or session_obj.revoked
        or session_obj.expires_at <= now()
    ):
        return None
    user = await db.get(User, session_obj.user_id)
    return user if user is not None and user.is_active else None


async def get_current_user_optional(
    db: AsyncSession = Depends(get_session),
    session_token: Annotated[str | None, Header(alias="Authorization")] = None,
) -> User | None:
    return await _get_current_user(session_token=session_token, db=db)


async def require_project_membership(
    project_id: str,
    current_user: User,
    db: AsyncSession = Depends(get_session),
) -> Project:
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid project id")
    project = await db.get(Project, pid)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if project.organization_id != current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this project")
    return project


async def require_organization_membership(
    organization_id: str,
    current_user: User,
    db: AsyncSession = Depends(get_session),
) -> Organization:
    try:
        oid = uuid.UUID(organization_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid organization id")
    org = await db.get(Organization, oid)
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    if org.id != current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this organization")
    return org


async def require_runtime_access(
    runtime_id: str | uuid.UUID,
    current_user: User,
    db: AsyncSession,
) -> "Runtime":
    """Load a runtime only when it belongs to the caller's tenant/project.

    Runtime identifiers are untrusted input.  Every route and background
    entrypoint should perform this check before reading or mutating a runtime.
    """
    from app.models.runtimes import Runtime

    try:
        rid = runtime_id if isinstance(runtime_id, uuid.UUID) else uuid.UUID(str(runtime_id))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid runtime id") from exc

    runtime = await db.get(Runtime, rid)
    if runtime is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Runtime not found")

    if runtime.project_id is not None:
        project = await db.get(Project, runtime.project_id)
        if project is None or project.organization_id != current_user.organization_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Runtime not found")
    elif runtime.user_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Runtime not found")
    return runtime


async def require_project_access(
    project_id: str | uuid.UUID,
    current_user: User,
    db: AsyncSession,
) -> Project:
    """Load a project scoped to the authenticated user's organization."""
    return await require_project_membership(str(project_id), current_user, db)


async def require_api_key_access(
    key_id: str | uuid.UUID,
    current_user: User,
    db: AsyncSession,
):
    """Load an API key owned by the caller or caller's organization."""
    from app.models.apikeys import ApiKey

    try:
        kid = key_id if isinstance(key_id, uuid.UUID) else uuid.UUID(str(key_id))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid api key id") from exc
    key = await db.get(ApiKey, kid)
    if key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
    allowed = (
        current_user.is_superuser
        or (key.user_id is not None and key.user_id == current_user.id)
        or (
            key.organization_id is not None
            and current_user.organization_id is not None
            and key.organization_id == current_user.organization_id
        )
    )
    if not allowed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
    return key
