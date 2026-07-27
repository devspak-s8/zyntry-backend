from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.organizations import TimestampMixin, UUIDMixin


class RequestLog(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "request_logs"

    project_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[int] = mapped_column(Integer, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    cost: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    completed_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
