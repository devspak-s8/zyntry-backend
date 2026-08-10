from __future__ import annotations

import logging
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Body, Cookie, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_session
from app.core.redis import redis_client
from app.core.security import (
    generate_session_token,
    generate_verification_token,
    hash_password,
    hash_token,
    now,
    verification_token_candidates,
    verify_password,
)
from app.models.email_verification_tokens import EmailVerificationToken
from app.models.organizations import Organization
from app.models.password_reset_tokens import PasswordResetToken
from app.models.refresh_tokens import RefreshToken
from app.models.sessions import Session
from app.models.users import User
from app.schemas.auth import AuthMeResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


async def _get_user_by_email(session: AsyncSession, email: str) -> User | None:
    normalized_email = email.strip().lower()
    result = await session.execute(
        select(User).where(func.lower(User.email) == normalized_email)
    )
    return result.scalar_one_or_none()


async def _create_session(session: AsyncSession, response: Response, user: User) -> None:
    token = generate_session_token()
    token_hash = hash_token(token)
    expires_at = now() + timedelta(minutes=settings.SESSION_TOKEN_TTL_MINUTES)

    session_obj = Session(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    session.add(session_obj)
    await session.flush()

    response.set_cookie(
        key="zyntra_session",
        value=token,
        httponly=True,
        secure=not settings.APP_DEBUG,
        samesite="none" if not settings.APP_DEBUG else "lax",
        max_age=settings.SESSION_TOKEN_TTL_MINUTES * 60,
        path="/",
    )


async def _create_refresh_token(session: AsyncSession, user: User) -> str:
    token = generate_session_token()
    token_hash = hash_token(token)
    expires_at = now() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    refresh_obj = RefreshToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    session.add(refresh_obj)
    await session.flush()
    return token


def _set_refresh_cookie(response: Response, token: str) -> None:
    max_age = settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
    response.set_cookie(
        key="zyntra_refresh",
        value=token,
        httponly=True,
        secure=not settings.APP_DEBUG,
        samesite="none" if not settings.APP_DEBUG else "lax",
        max_age=max_age,
        path="/",
    )


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    response: Response,
    email: Annotated[str, Body(embed=True)],
    password: Annotated[str, Body(embed=True)],
    name: Annotated[str | None, Body(embed=True)] = None,
    db: AsyncSession = Depends(get_session),
) -> AuthMeResponse:
    if len(password) < settings.PASSWORD_MIN_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"Password must be at least {settings.PASSWORD_MIN_LENGTH} characters",
        )

    existing = await _get_user_by_email(db, email)
    if existing is not None:
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        email=email,
        name=name,
        hashed_password=hash_password(password),
    )
    db.add(user)
    await db.flush()

    organization = Organization(
        name=f"{name or email}'s Organization",
        slug=f"org-{user.id.hex[:8]}",
    )
    db.add(organization)
    await db.flush()
    user.organization_id = organization.id
    await db.flush()

    token = generate_verification_token()
    token_hash = hash_token(token)
    expires_at = now() + timedelta(hours=24)

    verification_obj = EmailVerificationToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    db.add(verification_obj)
    await db.commit()

    try:
        from app.services.notifications.publishers import (
            send_verification_email as _send_verification_email,
        )

        result = await _send_verification_email(email, name, token)
        if not result.get("success"):
            logger.warning("Verification email failed for %s: %s", email, result.get("error"))
    except Exception:
        logger.exception("Failed to send verification email to %s", email)

    try:
        from app.events import NotificationEvent
        from app.services.notifications import enqueue_notification

        event = NotificationEvent(
            event_type="auth.welcome",
            recipient=email,
            data={"user_name": name},
            category="general",
        )
        enqueue_notification(event)
    except Exception:
        logger.exception("Failed to fire welcome email for %s", email)

    await _create_session(db, response, user)
    refresh_token = await _create_refresh_token(db, user)
    _set_refresh_cookie(response, refresh_token)
    await db.commit()

    return AuthMeResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        organization_id=user.organization_id,
        is_active=user.is_active,
        email_verified=user.email_verified,
    )


@router.post("/login")
async def login(
    response: Response,
    email: Annotated[str, Body(embed=True)],
    password: Annotated[str, Body(embed=True)],
    db: AsyncSession = Depends(get_session),
) -> AuthMeResponse:
    user = await _get_user_by_email(db, email)
    if user is None or user.hashed_password is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    await _create_session(db, response, user)
    refresh_token = await _create_refresh_token(db, user)
    _set_refresh_cookie(response, refresh_token)
    await db.commit()

    return AuthMeResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        organization_id=user.organization_id,
        is_active=user.is_active,
        email_verified=user.email_verified,
    )


@router.post("/logout")
async def logout(
    response: Response,
    session_token: Annotated[str | None, Cookie(alias="zyntra_session")] = None,
    db: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    if session_token is not None:
        await redis_client.delete(f"session:{session_token}")
        token_hash = hash_token(session_token)
        result = await db.execute(select(Session).where(Session.token_hash == token_hash))
        session_obj = result.scalar_one_or_none()
        if session_obj is not None:
            session_obj.revoked = True
            await db.commit()

    response.delete_cookie(key="zyntra_session", path="/")
    response.delete_cookie(key="zyntra_refresh", path="/")
    return {"message": "Logged out"}


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all(
    session_token: Annotated[str | None, Cookie(alias="zyntra_session")] = None,
    db: AsyncSession = Depends(get_session),
) -> None:
    if session_token is not None:
        token_hash = hash_token(session_token)
        result = await db.execute(select(Session).where(Session.token_hash == token_hash))
        session_obj = result.scalar_one_or_none()
        if session_obj is not None:
            sessions = await db.execute(
                select(Session).where(Session.user_id == session_obj.user_id)
            )
            for s in sessions.scalars().all():
                s.revoked = True

            refresh_tokens = await db.execute(
                select(RefreshToken).where(RefreshToken.user_id == session_obj.user_id)
            )
            for rt in refresh_tokens.scalars().all():
                rt.revoked = True

            await db.commit()

    return None


@router.post("/refresh")
async def refresh(
    response: Response,
    refresh_token: Annotated[str | None, Cookie(alias="zyntra_refresh")] = None,
    db: AsyncSession = Depends(get_session),
) -> AuthMeResponse:
    if refresh_token is None:
        raise HTTPException(status_code=401, detail="Refresh token missing")

    token_hash = hash_token(refresh_token)
    result = await db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    refresh_obj = result.scalar_one_or_none()

    if refresh_obj is None or refresh_obj.revoked or refresh_obj.expires_at <= now():
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    user = await db.get(User, refresh_obj.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    refresh_obj.revoked = True

    await _create_session(db, response, user)
    new_refresh = await _create_refresh_token(db, user)
    _set_refresh_cookie(response, new_refresh)
    await db.commit()

    return AuthMeResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        organization_id=user.organization_id,
        is_active=user.is_active,
        email_verified=user.email_verified,
    )


@router.get("/me", response_model=AuthMeResponse)
async def me(
    session_token: Annotated[str | None, Cookie(alias="zyntra_session")] = None,
    db: AsyncSession = Depends(get_session),
) -> AuthMeResponse:
    if session_token is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    token_hash = hash_token(session_token)
    result = await db.execute(select(Session).where(Session.token_hash == token_hash))
    session_obj = result.scalar_one_or_none()

    if session_obj is None or session_obj.revoked:
        raise HTTPException(status_code=401, detail="Invalid session")

    if session_obj.expires_at <= now():
        raise HTTPException(status_code=401, detail="Session expired")

    user = await db.get(User, session_obj.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid session")

    return AuthMeResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        organization_id=user.organization_id,
        is_active=user.is_active,
        email_verified=user.email_verified,
    )


@router.post("/forgot-password")
async def forgot_password(
    email: Annotated[str, Body(embed=True)],
    db: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    user = await _get_user_by_email(db, email)
    if user is not None:
        token = generate_verification_token()
        token_hash = hash_token(token)
        expires_at = now() + timedelta(minutes=15)
        reset_obj = PasswordResetToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        db.add(reset_obj)
        await db.commit()
        try:
            from app.events import NotificationEvent
            from app.services.notifications import enqueue_notification

            event = NotificationEvent(
                event_type="auth.password_reset",
                recipient=user.email,
                data={"user_name": user.name, "token": token},
                category="security",
                sender_name="Zyntry Security",
                sender_email="security@zyntry.space",
            )
            enqueue_notification(event)
        except Exception:
            logger.exception("Failed to enqueue password reset email to %s", user.email)
    return {"message": "If an account exists with that email, a reset link has been sent."}


@router.post("/reset-password")
async def reset_password(
    reset_token: Annotated[str, Body(embed=True)],
    password: Annotated[str, Body(embed=True)],
    db: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    if len(password) < settings.PASSWORD_MIN_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"Password must be at least {settings.PASSWORD_MIN_LENGTH} characters",
        )
    if not reset_token.startswith("rst_") or len(reset_token) < 32:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    token_hash = hash_token(reset_token)
    result = await db.execute(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
    )
    reset_obj = result.scalar_one_or_none()

    if reset_obj is None or reset_obj.used or reset_obj.expires_at <= now():
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    user = await db.get(User, reset_obj.user_id)
    if user is None:
        raise HTTPException(status_code=400, detail="Invalid reset token")

    user.hashed_password = hash_password(password)
    reset_obj.used = True
    await db.commit()
    try:
        from app.events import NotificationEvent
        from app.services.notifications import enqueue_notification

        event = NotificationEvent(
            event_type="auth.password_changed",
            recipient=user.email,
            data={"user_name": user.name},
            category="security",
            sender_name="Zyntry Security",
            sender_email="security@zyntry.space",
        )
        enqueue_notification(event)
    except Exception:
        logger.exception("Failed to enqueue password changed email to %s", user.email)
    return {"message": "Password has been reset."}


@router.post("/verify-reset-code")
async def verify_reset_code(
    email: Annotated[str, Body(embed=True)],
    code: Annotated[str, Body(embed=True)],
    db: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    """Consume an emailed code and exchange it for a short-lived reset token."""

    normalized_code = code.strip()
    if len(normalized_code) != 6 or not normalized_code.isalnum():
        raise HTTPException(status_code=400, detail="Invalid or expired reset code")

    user = await _get_user_by_email(db, email)
    if user is None:
        raise HTTPException(status_code=400, detail="Invalid or expired reset code")

    code_hashes = [
        hash_token(value) for value in verification_token_candidates(normalized_code)
    ]
    result = await db.execute(
        select(PasswordResetToken)
        .where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.token_hash.in_(code_hashes),
        )
        .order_by(PasswordResetToken.created_at.desc())
        .limit(1)
    )
    code_obj = result.scalar_one_or_none()

    if code_obj is None or code_obj.used or code_obj.expires_at <= now():
        raise HTTPException(status_code=400, detail="Invalid or expired reset code")

    raw_reset_token = f"rst_{generate_session_token()}"
    reset_obj = PasswordResetToken(
        user_id=user.id,
        token_hash=hash_token(raw_reset_token),
        expires_at=now() + timedelta(minutes=10),
    )
    code_obj.used = True
    db.add(reset_obj)
    await db.commit()

    return {"reset_token": raw_reset_token}


@router.post("/verify-email")
async def verify_email(
    token: Annotated[str, Body(embed=True)],
    db: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    token_hashes = [hash_token(value) for value in verification_token_candidates(token)]
    result = await db.execute(
        select(EmailVerificationToken)
        .where(EmailVerificationToken.token_hash.in_(token_hashes))
        .limit(1)
    )
    verification_obj = result.scalar_one_or_none()

    if verification_obj is None or verification_obj.used or verification_obj.expires_at <= now():
        raise HTTPException(status_code=400, detail="Invalid or expired verification token")

    user = await db.get(User, verification_obj.user_id)
    if user is None:
        raise HTTPException(status_code=400, detail="Invalid verification token")

    user.email_verified = True
    verification_obj.used = True
    await db.commit()
    try:
        from app.events import NotificationEvent
        from app.services.notifications import enqueue_notification

        event = NotificationEvent(
            event_type="auth.email_verified",
            recipient=user.email,
            data={"user_name": user.name},
            category="security",
            sender_name="Zyntry Security",
            sender_email="security@zyntry.space",
        )
        enqueue_notification(event)
    except Exception:
        logger.exception("Failed to enqueue email verified confirmation to %s", user.email)
    return {"message": "Email verified successfully"}


@router.post("/resend-verification")
async def resend_verification(
    email: Annotated[str, Body(embed=True)],
    db: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    user = await _get_user_by_email(db, email)
    if user is None:
        msg = "If an account exists with that email, a verification link has been sent."
        return {"message": msg}

    if user.email_verified:
        return {"message": "Email is already verified"}

    result = await db.execute(
        select(EmailVerificationToken).where(EmailVerificationToken.user_id == user.id)
    )
    existing = result.scalar_one_or_none()
    token = generate_verification_token()
    token_hash = hash_token(token)
    expires_at = now() + timedelta(hours=24)

    if existing is not None:
        existing.token_hash = token_hash
        existing.expires_at = expires_at
        existing.used = False
    else:
        verification_obj = EmailVerificationToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        db.add(verification_obj)

    await db.commit()
    try:
        from app.events import NotificationEvent
        from app.services.notifications import enqueue_notification

        event = NotificationEvent(
            event_type="auth.verify_email",
            recipient=email,
            data={"user_name": user.name, "token": token},
            category="security",
            sender_name="Zyntry Security",
            sender_email="security@zyntry.space",
        )
        enqueue_notification(event)
    except Exception:
        logger.exception("Failed to enqueue verification email to %s", email)

    return {"message": "If an account exists with that email, a verification link has been sent."}
