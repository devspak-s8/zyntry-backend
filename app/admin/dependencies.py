from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.auth import (
    check_ip_allowlist,
    check_ip_not_banned,
    decode_token,
    extract_token_from_request,
    get_client_ip,
)
from app.admin.constants import ROLE_PERMISSIONS, AdminRole, Permission
from app.admin.models import AdminUser, IPAllowList, IPRecord
from app.core.config import settings
from app.core.database import get_session
from app.models.users import User


class AdminContext:
    def __init__(self, admin_id: uuid.UUID, user_id: uuid.UUID, role: AdminRole, email: str, permissions: set[Permission], mfa_verified: bool) -> None:
        self.admin_id = admin_id
        self.user_id = user_id
        self.role = role
        self.email = email
        self.permissions = permissions
        self.mfa_verified = mfa_verified

    def is_super_admin(self) -> bool:
        return self.role == AdminRole.SUPER_ADMIN

    def has_permission(self, permission: Permission) -> bool:
        return permission in self.permissions

    def require_permission(self, permission: Permission) -> None:
        if not self.has_permission(permission):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")


async def get_admin_context(request: Request, db: AsyncSession = Depends(get_session)) -> AdminContext:
    token = extract_token_from_request(request)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    payload = decode_token(token)
    if payload.get("type") != "admin_access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")

    admin_id = uuid.UUID(payload["admin_id"])
    user_id = uuid.UUID(payload["user_id"])
    role = AdminRole(payload["role"])
    mfa_verified = payload.get("mfa_verified", False)

    result = await db.execute(select(AdminUser).where(AdminUser.id == admin_id))
    admin_user = result.scalar_one_or_none()
    if admin_user is None or not admin_user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin user not found")

    result2 = await db.execute(select(User).where(User.id == user_id))
    user = result2.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin user inactive")

    permissions = ROLE_PERMISSIONS.get(role, set())

    if settings.ADMIN_IP_ALLOWLIST:
        client_ip = get_client_ip(request)
        result3 = await db.execute(select(IPAllowList).where(IPAllowList.ip_address == client_ip, IPAllowList.is_active == True))
        allowlist = result3.scalars().all()
        if not check_ip_allowlist(client_ip, allowlist):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="IP not allowed")

    if settings.ADMIN_IP_BAN_CHECK:
        client_ip = get_client_ip(request)
        result4 = await db.execute(select(IPRecord).where(IPRecord.ip_address == client_ip))
        ip_record = result4.scalar_one_or_none()
        if not check_ip_not_banned(client_ip, ip_record):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="IP is banned")

    return AdminContext(admin_id=admin_id, user_id=user_id, role=role, email=user.email, permissions=permissions, mfa_verified=mfa_verified)


def require_permission(permission: Permission):
    async def _dependency(context: AdminContext = Depends(get_admin_context)) -> AdminContext:
        if not context.has_permission(permission):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return context
    return _dependency


def require_super_admin():
    async def _dependency(context: AdminContext = Depends(get_admin_context)) -> AdminContext:
        if not context.is_super_admin():
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super admin access required")
        return context
    return _dependency


async def _get_allowlist_enabled() -> bool:
    return bool(settings.ADMIN_IP_ALLOWLIST)


async def get_admin_context_optional(request: Request, db: AsyncSession = Depends(get_session)) -> AdminContext | None:
    try:
        return await get_admin_context(request, db)
    except HTTPException:
        return None


async def get_current_super_admin(request: Request, db: AsyncSession = Depends(get_session)) -> AdminUser:
    token = extract_token_from_request(request)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    payload = decode_token(token)
    admin_id = uuid.UUID(payload["admin_id"])

    result = await db.execute(select(AdminUser).where(AdminUser.id == admin_id))
    admin_user = result.scalar_one_or_none()
    if admin_user is None or not admin_user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin user not found")
    if not admin_user.is_super_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super admin access required")
    return admin_user


async def get_current_mfa_verified(request: Request, db: AsyncSession = Depends(get_session)) -> AdminUser:
    token = extract_token_from_request(request)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    payload = decode_token(token)
    if not payload.get("mfa_verified", False):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="MFA verification required")

    admin_id = uuid.UUID(payload["admin_id"])
    result = await db.execute(select(AdminUser).where(AdminUser.id == admin_id))
    admin_user = result.scalar_one_or_none()
    if admin_user is None or not admin_user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin user not found")
    return admin_user


GetAdminContext = Annotated[AdminContext, Depends(get_admin_context)]
GetSuperAdmin = Annotated[AdminUser, Depends(get_current_super_admin)]