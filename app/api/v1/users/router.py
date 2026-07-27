from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.core.database import get_session
from app.models.users import User
from app.repositories import UnitOfWork
from app.schemas.users import UserCreate, UserRead, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserRead])
async def list_users(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> list[UserRead]:
    result = await db.execute(select(User))
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
