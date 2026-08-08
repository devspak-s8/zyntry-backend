from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.core.database import get_session
from app.models.users import User
from app.repositories import UnitOfWork
from app.schemas.users import UserRead, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


def _require_superuser(current_user: User) -> None:
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Superadmin access required")


@router.get("", response_model=list[UserRead])
async def list_users(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[UserRead]:
    _require_superuser(current_user)
    result = await db.execute(
        select(User).order_by(User.created_at.desc()).limit(limit).offset(offset)
    )
    users = result.scalars().all()
    return [
        UserRead(
            id=u.id,
            email=u.email,
            name=u.name,
            is_active=u.is_active,
            created_at=u.created_at,
        )
        for u in users
    ]


@router.get("/{user_id}", response_model=UserRead)
async def get_user(
    user_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> UserRead:
    import uuid

    _require_superuser(current_user)
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user id")

    user = await db.get(User, uid)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    return UserRead(
        id=user.id,
        email=user.email,
        name=user.name,
        is_active=user.is_active,
        created_at=user.created_at,
    )


@router.patch("/{user_id}", response_model=UserRead)
async def update_user(
    user_id: str,
    body: UserUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> UserRead:
    import uuid

    _require_superuser(current_user)
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user id")

    user = await db.get(User, uid)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    uow = UnitOfWork(db)
    try:
        update_data: dict[str, object] = {}
        if body.email is not None:
            update_data["email"] = body.email
        if body.name is not None:
            update_data["name"] = body.name
        if update_data:
            await uow.users.update(user, **update_data)
            await uow.commit()
    except IntegrityError:
        await uow.rollback()
        raise HTTPException(status_code=409, detail="Email already in use")
    except Exception as exc:
        await uow.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to update user: {exc}")

    return UserRead(
        id=user.id,
        email=user.email,
        name=user.name,
        is_active=user.is_active,
        created_at=user.created_at,
    )


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> None:
    import uuid

    _require_superuser(current_user)
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user id")

    user = await db.get(User, uid)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    uow = UnitOfWork(db)
    try:
        await uow.users.delete(user)
        await uow.commit()
    except Exception as exc:
        await uow.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete user: {exc}")


@router.get("/me/settings", response_model=dict[str, object])
async def get_user_settings(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    return current_user.settings or {}


@router.patch("/me/settings", response_model=dict[str, object])
async def update_user_settings(
    body: dict[str, object],
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    uow = UnitOfWork(db)
    try:
        await uow.users.update(current_user, settings=body)
        await uow.commit()
    except Exception as exc:
        await uow.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to update settings: {exc}")
    return body


@router.post("/me/2fa/enable")
async def enable_two_factor(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    import secrets

    secret = secrets.token_base32()
    uow = UnitOfWork(db)
    try:
        await uow.users.update(current_user, two_factor_secret=secret, two_factor_enabled=True)
        await uow.commit()
    except Exception as exc:
        await uow.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to enable 2FA: {exc}")
    return {"secret": secret, "status": "enabled"}


@router.post("/me/2fa/disable")
async def disable_two_factor(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    uow = UnitOfWork(db)
    try:
        await uow.users.update(current_user, two_factor_secret=None, two_factor_enabled=False)
        await uow.commit()
    except Exception as exc:
        await uow.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to disable 2FA: {exc}")
    return {"status": "disabled"}


@router.post("/me/tokens/revoke-all")
async def revoke_all_tokens(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    uow = UnitOfWork(db)
    try:
        await uow.users.update(
            current_user, settings={**(current_user.settings or {}), "tokens_revoked": True}
        )
        await uow.commit()
    except Exception as exc:
        await uow.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to revoke tokens: {exc}")
    return {"status": "all tokens revoked"}
