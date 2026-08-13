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
    if session_obj is None or session_obj.revoked:
        return None
    user = await db.get(User, session_obj.user_id)
    return user


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
