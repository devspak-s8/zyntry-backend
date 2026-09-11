from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.organizations import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.projects import Project


class ModelProvider(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "model_providers"

    name: Mapped[str] = mapped_column(String(64), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project: Mapped[Project] = relationship(back_populates="providers")
