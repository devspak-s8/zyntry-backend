from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.organizations import ORMModel


class UserCreate(ORMModel):
    email: EmailStr
    name: str | None = None
    password: str = Field(min_length=8)


class UserUpdate(ORMModel):
    email: EmailStr | None = None
    name: str | None = None
    settings: dict[str, object] | None = None
    two_factor_enabled: bool | None = None
    two_factor_secret: str | None = None


class UserRead(ORMModel):
    id: uuid.UUID
    email: EmailStr
    name: str | None
    is_active: bool
    created_at: datetime
    two_factor_enabled: bool = False
    settings: dict[str, object] | None = None
