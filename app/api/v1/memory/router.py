from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.core.database import get_session
from app.models.users import User
from app.repositories import UnitOfWork
from app.schemas.memory import MemoryRecordCreate, MemoryRecordRead, MemoryToggleRequest
from app.services.memory import MemoryService

router = APIRouter(prefix="/memory", tags=["memory"])


@router.get("", response_model=list[MemoryRecordRead])
async def list_memory_records(
    current_user: Annotated[User, Depends(get_current_user)],
    project_id: str,
    db: AsyncSession = Depends(get_session),
) -> list[MemoryRecordRead]:
    uow = UnitOfWork(db)
    service = MemoryService(uow)
    records = await service.list_records(project_id)
    return [
        MemoryRecordRead(
            id=r["id"],
            key=r["key"],
            value=r.get("value", {}),
            content=r.get("content"),
            project_id=project_id,
            user_id=current_user.id,
            created_at=r.get("created_at", ""),
            updated_at=r.get("created_at", ""),
        )
        for r in records
    ]


@router.post("", response_model=MemoryRecordRead, status_code=status.HTTP_201_CREATED)
async def create_memory_record(
    body: MemoryRecordCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> MemoryRecordRead:
    uow = UnitOfWork(db)
    service = MemoryService(uow)
    record = await service.create_record(body)
    return MemoryRecordRead(
        id=record["id"],
        key=record["key"],
        value=record.get("value", {}),
        content=record.get("content"),
        project_id=body.project_id,
        user_id=body.user_id or str(current_user.id),
        created_at="",
        updated_at="",
    )


@router.post("/toggle")
async def toggle_project_memory(
    body: MemoryToggleRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> dict:
    uow = UnitOfWork(db)
    service = MemoryService(uow)
    result = await service.toggle_project_memory(body)
    return result
