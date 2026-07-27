"""Add processed webhook events table for idempotency.

Revision ID: 0010_processed_webhook_events
Revises: 0009_seed_pricing
Create Date: 2026-07-25 21:45:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0010_processed_webhook_events"
down_revision: str | None = "0009_seed_pricing"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "processed_webhook_events",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("event_id", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id"),
    )
    op.create_index("ix_processed_webhook_events_event_id", "processed_webhook_events", ["event_id"])
    op.create_index("ix_processed_webhook_events_source", "processed_webhook_events", ["source"])
    op.create_index("ix_processed_webhook_events_event_type", "processed_webhook_events", ["event_type"])
    op.create_index("ix_processed_webhook_events_status", "processed_webhook_events", ["status"])
    op.create_index("ix_processed_webhook_events_received_at", "processed_webhook_events", ["received_at"])


def downgrade() -> None:
    op.drop_index("ix_processed_webhook_events_received_at", table_name="processed_webhook_events")
    op.drop_index("ix_processed_webhook_events_status", table_name="processed_webhook_events")
    op.drop_index("ix_processed_webhook_events_event_type", table_name="processed_webhook_events")
    op.drop_index("ix_processed_webhook_events_source", table_name="processed_webhook_events")
    op.drop_index("ix_processed_webhook_events_event_id", table_name="processed_webhook_events")
    op.drop_table("processed_webhook_events")
