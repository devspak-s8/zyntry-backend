from __future__ import annotations

import pytest
from sqlalchemy import select

from app.admin.constants import AdminRole
from app.admin.models import AdminUser
from app.core.security import hash_password
from app.models.users import User
from scripts.seed_superadmin import _ensure_admin_record


@pytest.mark.asyncio
async def test_ensure_admin_record_creates_active_superadmin(db_session) -> None:
    user = User(
        email="seeded-admin@example.com",
        hashed_password=hash_password("strong-test-password"),
        is_active=True,
        is_superuser=True,
        email_verified=True,
    )
    db_session.add(user)

    await _ensure_admin_record(db_session, user)
    await db_session.flush()

    result = await db_session.execute(
        select(AdminUser).where(AdminUser.user_id == user.id)
    )
    admin_user = result.scalar_one()
    assert admin_user.role == AdminRole.SUPER_ADMIN
    assert admin_user.is_active is True
