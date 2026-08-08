#!/usr/bin/env python3
"""Idempotently create or update the configured superadmin account."""

from __future__ import annotations

import asyncio
import os
import re

from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import async_session_factory
from app.core.security import hash_password, verify_password
from app.models.organizations import Organization
from app.models.users import User


def _admin_slug(email: str) -> str:
    local_part = email.split("@", 1)[0].lower()
    safe_part = re.sub(r"[^a-z0-9]+", "-", local_part).strip("-") or "admin"
    return f"superadmin-{safe_part}"[:255]


async def seed_superadmin() -> None:
    email = os.getenv("SUPERADMIN_EMAIL", "").strip().lower()
    password = os.getenv("SUPERADMIN_PASSWORD", "")
    name = os.getenv("SUPERADMIN_NAME", "Super Admin").strip() or "Super Admin"

    if not email and not password:
        print("Superadmin seed skipped: credentials are not configured.")
        return
    if not email or not password:
        raise RuntimeError(
            "SUPERADMIN_EMAIL and SUPERADMIN_PASSWORD must either both be set or both be empty"
        )
    if len(password) < settings.PASSWORD_MIN_LENGTH:
        raise RuntimeError(
            f"SUPERADMIN_PASSWORD must be at least {settings.PASSWORD_MIN_LENGTH} characters"
        )

    async with async_session_factory() as db:
        result = await db.execute(select(User).where(func.lower(User.email) == email))
        user = result.scalar_one_or_none()

        if user is None:
            slug = _admin_slug(email)
            org_result = await db.execute(
                select(Organization).where(Organization.slug == slug)
            )
            organization = org_result.scalar_one_or_none()
            if organization is None:
                organization = Organization(name=f"{name}'s Organization", slug=slug)
                db.add(organization)
                await db.flush()

            user = User(
                email=email,
                name=name,
                hashed_password=hash_password(password),
                organization_id=organization.id,
                is_active=True,
                is_superuser=True,
                email_verified=True,
            )
            db.add(user)
            action = "created"
        else:
            if not verify_password(password, user.hashed_password):
                user.hashed_password = hash_password(password)
            user.name = name
            user.is_active = True
            user.is_superuser = True
            user.email_verified = True

            if user.organization_id is None:
                slug = _admin_slug(email)
                org_result = await db.execute(
                    select(Organization).where(Organization.slug == slug)
                )
                organization = org_result.scalar_one_or_none()
                if organization is None:
                    organization = Organization(name=f"{name}'s Organization", slug=slug)
                    db.add(organization)
                    await db.flush()
                user.organization_id = organization.id
            action = "updated"

        await db.commit()
        print(f"Superadmin {action}: {email}")


if __name__ == "__main__":
    asyncio.run(seed_superadmin())
