from __future__ import annotations

import pytest
from sqlalchemy import select

from app.admin.auth import AdminAuth
from app.admin.constants import AdminRole
from app.admin.models import AdminSession, AdminUser
from app.core.security import hash_password, hash_token
from app.models.users import User


@pytest.mark.asyncio
async def test_admin_login_commits_revocable_session(db_session) -> None:
    password = "strong-admin-test-password"
    user = User(
        email="transaction-admin@example.com",
        hashed_password=hash_password(password),
        is_active=True,
        is_superuser=True,
        email_verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        AdminUser(
            user_id=user.id,
            role=AdminRole.SUPER_ADMIN,
            is_active=True,
        )
    )
    await db_session.commit()

    result = await AdminAuth(db_session).login(
        user.email,
        password,
        "127.0.0.1",
        "pytest",
    )

    # A rollback after login must not remove the session used to authorize the
    # next request.
    await db_session.rollback()
    session_result = await db_session.execute(
        select(AdminSession).where(
            AdminSession.token_hash == hash_token(result["access_token"])
        )
    )
    assert session_result.scalar_one_or_none() is not None
