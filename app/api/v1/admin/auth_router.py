from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.auth import AdminAuth, extract_token_from_request
from app.admin.constants import Permission
from app.admin.dependencies import (
    AdminContext,
    require_permission,
)
from app.admin.schemas import (
    AdminUserRead,
)
from app.core.database import get_session
from app.models.users import User

router = APIRouter(prefix="/admin", tags=["admin-auth"])


class AdminLoginRequest(BaseModel):
    email: str
    password: str
    ip_address: str | None = None
    user_agent: str | None = None


@router.post("/auth/login")
async def admin_login(
    request: Request,
    body: AdminLoginRequest | None = Body(default=None),
    email: str | None = Query(default=None),
    password: str | None = Query(default=None),
    ip_address: str | None = Query(default=None),
    user_agent: str | None = Query(default=None),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    email = body.email if body else email
    password = body.password if body else password
    ip_address = (body.ip_address if body else ip_address) or (request.client.host if request.client else "unknown")
    user_agent = (body.user_agent if body else user_agent) or request.headers.get("user-agent", "unknown")
    if not email or not password:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="email and password are required")
    auth = AdminAuth(db)
    result = await auth.login(email, password, ip_address, user_agent)
    return result


@router.post("/auth/refresh")
async def admin_refresh_token(
    refresh_token: str = Query(...),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    auth = AdminAuth(db)
    result = await auth.refresh_access(refresh_token)
    return result


@router.post("/auth/logout")
async def admin_logout(
    request: Request,
    ctx: AdminContext = Depends(require_permission(Permission.AUTH_LOGOUT)),
    db: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    token = extract_token_from_request(request)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    auth = AdminAuth(db)
    result = await auth.logout(token)
    return result


@router.get("/auth/me")
async def admin_me(
    ctx: AdminContext = Depends(require_permission(Permission.AUTH_LOGIN)),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user = await db.get(User, ctx.user_id)
    return {
        "id": str(ctx.user_id),
        "admin_id": str(ctx.admin_id),
        "user_id": str(ctx.user_id),
        "role": ctx.role.value,
        "email": ctx.email,
        "name": user.name if user else None,
        "organization_id": str(user.organization_id) if user and user.organization_id else None,
        "two_factor_enabled": bool(user.two_factor_enabled) if user else False,
        "mfa_verified": ctx.mfa_verified,
    }


@router.post("/auth/mfa/setup")
async def admin_mfa_setup(
    ctx: AdminContext = Depends(require_permission(Permission.AUTH_MFA)),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    auth = AdminAuth(db)
    result = await auth.setup_mfa(ctx.admin_id)
    return result


@router.post("/auth/mfa/verify")
async def admin_mfa_verify(
    code: str = Query(...),
    ctx: AdminContext = Depends(require_permission(Permission.AUTH_MFA)),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    auth = AdminAuth(db)
    result = await auth.verify_mfa(ctx.admin_id, code)
    return result


@router.post("/auth/mfa/disable")
async def admin_mfa_disable(
    ctx: AdminContext = Depends(require_permission(Permission.AUTH_MFA)),
    db: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    auth = AdminAuth(db)
    result = await auth.disable_mfa(ctx.admin_id)
    return result


@router.get("/users", response_model=list[AdminUserRead])
async def admin_list_users(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    ctx: AdminContext = Depends(require_permission(Permission.DASHBOARD_READ)),
    db: AsyncSession = Depends(get_session),
) -> list[AdminUserRead]:
    from app.admin.models import AdminUser
    result = await db.execute(
        select(AdminUser, User)
        .join(User, User.id == AdminUser.user_id)
        .order_by(AdminUser.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return [
        AdminUserRead(
            id=str(admin.id),
            email=user.email,
            name=user.name or "",
            role=admin.role.value if hasattr(admin.role, "value") else str(admin.role),
            is_active=admin.is_active and user.is_active,
            mfa_enabled=admin.mfa_enabled,
            created_at=admin.created_at.isoformat() if admin.created_at else "",
        )
        for admin, user in result.all()
    ]


@router.get("/users/{admin_id}", response_model=AdminUserRead)
async def admin_get_user(
    admin_id: str,
    ctx: AdminContext = Depends(require_permission(Permission.DASHBOARD_READ)),
    db: AsyncSession = Depends(get_session),
) -> AdminUserRead:
    from app.admin.models import AdminUser
    try:
        admin_uuid = __import__("uuid").UUID(admin_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid admin user id") from exc
    result = await db.execute(
        select(AdminUser, User)
        .join(User, User.id == AdminUser.user_id)
        .where(AdminUser.id == admin_uuid)
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Admin user not found")
    user, account = row
    return AdminUserRead(
        id=str(user.id),
        email=account.email,
        name=account.name or "",
        role=user.role.value if hasattr(user.role, "value") else str(user.role),
        is_active=user.is_active and account.is_active,
        mfa_enabled=user.mfa_enabled,
        created_at=user.created_at.isoformat() if user.created_at else "",
    )
