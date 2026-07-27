from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.organizations import TimestampMixin, UUIDMixin


class Model(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "models"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    family: Mapped[str | None] = mapped_column(String(64), nullable=True)
    context_window: Mapped[int | None] = mapped_column(nullable=True)
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Provider(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "providers"

    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
