from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt

from app.core.config import settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=10)).decode("utf-8")


def verify_password(plain: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        pass
    if len(hashed) == 64 and all(c in "0123456789abcdef" for c in hashed.lower()):
        return hashlib.sha256(plain.encode("utf-8")).hexdigest() == hashed
    return False


def generate_api_key(prefix: str = "zy") -> str:
    return f"{prefix}_{secrets.token_urlsafe(32)}"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_nonce(length: int = 32) -> str:
    return secrets.token_hex(length)


def generate_session_token() -> str:
    return secrets.token_urlsafe(48)


def sign_payload(payload: bytes, secret: str | None = None) -> str:
    key = (secret or settings.SECRET_KEY).encode("utf-8")
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def constant_time_compare(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)


def now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def timedelta_minutes(minutes: int) -> timedelta:
    return timedelta(minutes=minutes)
