from __future__ import annotations

import uuid
from datetime import UTC
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
from app.admin.models import AdminSession, AdminUser, IPAllowList, IPRecord
from app.core.config import settings
from app.core.database import get_session
from app.core.security import hash_token, now
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


def _claim_uuid(payload: dict, name: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(payload[name]))
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin token") from exc


async def _require_admin_session(token: str, payload: dict, db: AsyncSession) -> tuple[uuid.UUID, uuid.UUID, AdminSession]:
    """Validate the JWT *and* its revocable database session.

    A signed JWT is not sufficient for admin access: logout, role changes and
    incident response must be able to revoke an already-issued token.
    """
    if payload.get("type") != "admin_access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")
    admin_id = _claim_uuid(payload, "admin_id")
    user_id = _claim_uuid(payload, "user_id")
    result = await db.execute(select(AdminSession).where(AdminSession.token_hash == hash_token(token)))
    session = result.scalar_one_or_none()
    expires_at = getattr(session, "expires_at", None)
    if (
        session is None
        or session.revoked
        or expires_at is None
        or (expires_at.replace(tzinfo=UTC) if expires_at.tzinfo is None else expires_at) <= now()
        or session.admin_user_id != admin_id
        or session.user_id != user_id
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired or revoked")
    return admin_id, user_id, session


async def get_admin_context(request: Request, db: AsyncSession = Depends(get_session)) -> AdminContext:
    token = extract_token_from_request(request)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    payload = decode_token(token)
    admin_id, user_id, admin_session = await _require_admin_session(token, payload, db)
    mfa_verified = payload.get("mfa_verified", False)

    result = await db.execute(select(AdminUser).where(AdminUser.id == admin_id))
    admin_user = result.scalar_one_or_none()
    if admin_user is None or not admin_user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin user not found")

    result2 = await db.execute(select(User).where(User.id == user_id))
    user = result2.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin user inactive")

    # Roles are authoritative in the database. A still-valid token may carry
    # a stale role claim after an administrator's role is changed, so never
    # derive permissions from the claim alone.
    try:
        role = AdminRole(admin_user.role)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin role") from exc
    if admin_user.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin token subject")
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

    return AdminContext(
        admin_id=admin_id,
        user_id=user_id,
        role=role,
        email=user.email,
        permissions=permissions,
        mfa_verified=bool(mfa_verified and admin_user.mfa_verified and admin_session.mfa_verified),
    )


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
    admin_id, user_id, _ = await _require_admin_session(token, payload, db)

    result = await db.execute(select(AdminUser).where(AdminUser.id == admin_id))
    admin_user = result.scalar_one_or_none()
    if admin_user is None or not admin_user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin user not found")
    if admin_user.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin token subject")
    try:
        role = AdminRole(admin_user.role)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin role") from exc
    if role != AdminRole.SUPER_ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super admin access required")
    return admin_user


async def get_current_mfa_verified(request: Request, db: AsyncSession = Depends(get_session)) -> AdminUser:
    token = extract_token_from_request(request)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    payload = decode_token(token)
    if not payload.get("mfa_verified", False):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="MFA verification required")

    admin_id, user_id, admin_session = await _require_admin_session(token, payload, db)
    result = await db.execute(select(AdminUser).where(AdminUser.id == admin_id))
    admin_user = result.scalar_one_or_none()
    if admin_user is None or not admin_user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin user not found")
    if admin_user.user_id != user_id or not admin_user.mfa_verified or not admin_session.mfa_verified:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="MFA verification required")
    return admin_user


GetAdminContext = Annotated[AdminContext, Depends(get_admin_context)]
GetSuperAdmin = Annotated[AdminUser, Depends(get_current_super_admin)]
