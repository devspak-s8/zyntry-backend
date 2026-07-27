from __future__ import annotations

import uuid

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.organizations import TimestampMixin, UUIDMixin


class Event(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "events"

    project_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
