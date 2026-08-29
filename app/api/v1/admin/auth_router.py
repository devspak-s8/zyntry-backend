from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
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

router = APIRouter(prefix="/admin", tags=["admin-auth"])


@router.post("/auth/login")
async def admin_login(
    email: str = Query(...),
    password: str = Query(...),
    ip_address: str = Query(...),
    user_agent: str = Query(...),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
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
    return {
        "admin_id": str(ctx.admin_id),
        "user_id": str(ctx.user_id),
        "role": ctx.role.value,
        "email": ctx.email,
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
    from app.admin.repositories import AdminUserRepository
    repo = AdminUserRepository(db)
    users = await repo.list_all(limit=limit, offset=offset)
    return [
        AdminUserRead(
            id=str(u.id),
            email="",
            name="",
            role=u.role.value,
            is_active=u.is_active,
            mfa_enabled=u.mfa_enabled,
            created_at=u.created_at.isoformat() if u.created_at else "",
        )
        for u in users
    ]


@router.get("/users/{admin_id}", response_model=AdminUserRead)
async def admin_get_user(
    admin_id: str,
    ctx: AdminContext = Depends(require_permission(Permission.DASHBOARD_READ)),
    db: AsyncSession = Depends(get_session),
) -> AdminUserRead:
    from app.admin.repositories import AdminUserRepository
    repo = AdminUserRepository(db)
    user = await repo.get_by_id(admin_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Admin user not found")
    return AdminUserRead(
        id=str(user.id),
        email="",
        name="",
        role=user.role.value,
        is_active=user.is_active,
        mfa_enabled=user.mfa_enabled,
        created_at=user.created_at.isoformat() if user.created_at else "",
    )
