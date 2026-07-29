"""Add provider_connections and onboarding_states tables.

Revision ID: 0011_provider_connections_onboarding
Revises: 0010_processed_webhook_events
Create Date: 2026-07-28 08:15:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "0011_provider_connections_onboarding"
down_revision: str | None = "0010_processed_webhook_events"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    from app.core.database import Base

    conn = op.get_bind()
    Base.metadata.create_all(
        bind=conn,
        tables=[
            Base.metadata.tables.get("provider_connections"),
            Base.metadata.tables.get("onboarding_states"),
        ],
    )


def downgrade() -> None:
    from app.core.database import Base

    conn = op.get_bind()
    Base.metadata.drop_all(
        bind=conn,
        tables=[
            Base.metadata.tables.get("onboarding_states"),
            Base.metadata.tables.get("provider_connections"),
        ],
    )
