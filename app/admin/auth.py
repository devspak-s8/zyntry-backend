from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.constants import ROLE_PERMISSIONS, AdminRole, Permission
from app.admin.models import AdminSession, AdminUser, IPAllowList, IPRecord
from app.core.config import settings
from app.core.security import hash_token, verify_password
from app.models.users import User

TOTP_TIME_STEP = 30
TOTP_DIGITS = 6
TOTP_HASH = hashlib.sha1


def _b32_decode(encoded: str) -> bytes:
    padded = encoded.upper() + "=" * ((8 - len(encoded) % 8) % 8)
    return base64.b32decode(padded)


def generate_totp(secret: str, timestamp: float | None = None) -> str:
    if timestamp is None:
        timestamp = time.time()
    key = _b32_decode(secret)
    counter = int(timestamp // TOTP_TIME_STEP)
    msg = struct.pack(">Q", counter)
    h = hmac.new(key, msg, TOTP_HASH).digest()
    offset = h[-1] & 0x0F
    code = (h[offset] & 0x7F) << 24 | (h[offset + 1] & 0xFF) << 16 | (h[offset + 2] & 0xFF) << 8 | (h[offset + 3] & 0xFF)
    return str(code % (10 ** TOTP_DIGITS)).zfill(TOTP_DIGITS)


def generate_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("utf-8")


def generate_totp_uri(secret: str, user_email: str) -> str:
    return f"otpauth://totp/Zyntra:{user_email}?secret={secret}&issuer=Zyntra&algorithm=SHA1&digits={TOTP_DIGITS}&period={TOTP_TIME_STEP}"


def verify_totp(secret: str, code: str, window: int = 1) -> bool:
    now = time.time()
    for i in range(-window, window + 1):
        if generate_totp(secret, now + i * TOTP_TIME_STEP) == code:
            return True
    return False


def _get_admin_role_permissions(role: AdminRole) -> set[Permission]:
    return ROLE_PERMISSIONS.get(role, set())


def has_permission(role: AdminRole, permission: Permission) -> bool:
    return permission in _get_admin_role_permissions(role)


def create_access_token(admin_id: uuid.UUID, user_id: uuid.UUID, role: AdminRole, mfa_verified: bool = False) -> str:
    now = datetime.now(UTC)
    payload = {
        "admin_id": str(admin_id),
        "user_id": str(user_id),
        "role": role.value,
        "mfa_verified": mfa_verified,
        "iat": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        "type": "admin_access",
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(admin_id: uuid.UUID, user_id: uuid.UUID) -> str:
    now = datetime.now(UTC)
    payload = {
        "admin_id": str(admin_id),
        "user_id": str(user_id),
        "iat": now,
        "exp": now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        "type": "admin_refresh",
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def extract_token_from_request(request: Request) -> str | None:
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header[7:]
    return None


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check_ip_allowlist(ip_address: str, allowlist: list[IPAllowList]) -> bool:
    for entry in allowlist:
        if entry.ip_address == ip_address and entry.is_active:
            return True
    return False


def check_ip_not_banned(ip_address: str, ip_record: IPRecord | None) -> bool:
    if ip_record is None:
        return True
    if ip_record.is_banned:
        if ip_record.ban_type == "permanent":
            return False
        if ip_record.ban_expires_at and ip_record.ban_expires_at > datetime.now(UTC):
            return False
    return True


def require_mfa_for_sensitive(role: AdminRole) -> bool:
    return role in (AdminRole.SUPER_ADMIN, AdminRole.SECURITY_ANALYST, AdminRole.BILLING_ADMIN)


class AdminAuth:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def login(self, email: str, password: str, ip_address: str, user_agent: str) -> dict[str, Any]:
        result = await self.db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if user is None or not user.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

        if not verify_password(password, user.hashed_password):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

        result2 = await self.db.execute(select(AdminUser).where(AdminUser.user_id == user.id))
        admin_user = result2.scalar_one_or_none()
        if admin_user is None or not admin_user.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not an admin user")

        access_token = create_access_token(admin_user.id, user.id, AdminRole(admin_user.role))
        refresh_token = create_refresh_token(admin_user.id, user.id)

        token_hash = hash_token(access_token)
        session = AdminSession(
            user_id=user.id,
            admin_user_id=admin_user.id,
            token_hash=token_hash,
            ip_address=ip_address,
            user_agent=user_agent,
            expires_at=datetime.now(UTC) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        )
        self.db.add(session)
        await self.db.flush()

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
"role": AdminRole(admin_user.role).value,
            "mfa_verified": admin_user.mfa_verified,
        }

    async def verify_access_token(self, token: str) -> dict[str, Any]:
        payload = decode_token(token)
        if payload.get("type") != "admin_access":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")

        admin_id = uuid.UUID(payload["admin_id"])
        token_hash = hash_token(token)

        result = await self.db.execute(select(AdminSession).where(AdminSession.token_hash == token_hash))
        session = result.scalar_one_or_none()
        if session is None or session.revoked or session.expires_at < datetime.now(UTC):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired or revoked")

        result2 = await self.db.execute(select(AdminUser).where(AdminUser.id == admin_id))
        admin_user = result2.scalar_one_or_none()
        if admin_user is None or not admin_user.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin user inactive")

        return {"admin_id": admin_id, "user_id": uuid.UUID(payload["user_id"]), "role": AdminRole(admin_user.role), "mfa_verified": payload.get("mfa_verified", False)}

    async def refresh_access(self, refresh_token_str: str) -> dict[str, Any]:
        payload = decode_token(refresh_token_str)
        if payload.get("type") != "admin_refresh":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")

        admin_id = uuid.UUID(payload["admin_id"])
        result = await self.db.execute(select(AdminUser).where(AdminUser.id == admin_id))
        admin_user = result.scalar_one_or_none()
        if admin_user is None or not admin_user.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin user not found")

        access_token = create_access_token(admin_user.id, uuid.UUID(payload["user_id"]), AdminRole(admin_user.role), admin_user.mfa_verified)
        new_refresh = create_refresh_token(admin_user.id, uuid.UUID(payload["user_id"]))
        return {"access_token": access_token, "refresh_token": new_refresh, "token_type": "bearer", "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60, "role": AdminRole(admin_user.role).value, "mfa_verified": admin_user.mfa_verified}

    async def logout(self, token: str) -> dict[str, str]:
        token_hash = hash_token(token)
        result = await self.db.execute(select(AdminSession).where(AdminSession.token_hash == token_hash))
        session = result.scalar_one_or_none()
        if session:
            session.revoked = True
            await self.db.flush()
        return {"message": "Logged out successfully"}

    async def logout_all(self, admin_user_id: uuid.UUID) -> dict[str, str]:
        result = await self.db.execute(select(AdminSession).where(AdminSession.admin_user_id == admin_user_id))
        sessions = result.scalars().all()
        for session in sessions:
            session.revoked = True
        await self.db.flush()
        return {"message": "All sessions revoked"}

    async def setup_mfa(self, admin_id: uuid.UUID) -> dict[str, Any]:
        result = await self.db.execute(select(AdminUser).where(AdminUser.id == admin_id))
        admin_user = result.scalar_one_or_none()
        if admin_user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Admin user not found")

        secret = generate_totp_secret()
        admin_user.mfa_secret = secret
        admin_user.mfa_enabled = True
        await self.db.flush()

        return {"secret": secret, "uri": generate_totp_uri(secret, admin_user.user_id)}

    async def verify_mfa(self, admin_id: uuid.UUID, code: str) -> dict[str, Any]:
        result = await self.db.execute(select(AdminUser).where(AdminUser.id == admin_id))
        admin_user = result.scalar_one_or_none()
        if admin_user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Admin user not found")

        if not admin_user.mfa_secret:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="MFA not set up")

        if not verify_totp(admin_user.mfa_secret, code):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid MFA code")

        admin_user.mfa_verified = True
        await self.db.flush()
        return {"message": "MFA verified successfully"}

    async def disable_mfa(self, admin_id: uuid.UUID) -> dict[str, str]:
        result = await self.db.execute(select(AdminUser).where(AdminUser.id == admin_id))
        admin_user = result.scalar_one_or_none()
        if admin_user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Admin user not found")

        admin_user.mfa_secret = None
        admin_user.mfa_enabled = False
        admin_user.mfa_verified = False
        await self.db.flush()
        return {"message": "MFA disabled successfully"}