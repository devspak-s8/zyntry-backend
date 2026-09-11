"""add provider funding monitoring

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "provider_funding_accounts",
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("account_label", sa.String(255), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="usd"),
        sa.Column("funding_mode", sa.String(32), nullable=False, server_default="manual"),
        sa.Column("monitor_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("auto_top_up_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("current_balance", sa.Numeric(18, 6), nullable=True),
        sa.Column("estimated_balance", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("minimum_balance", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("target_balance", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("max_top_up", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("daily_top_up_limit", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("daily_top_up_total", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("payment_method_ref", sa.String(255), nullable=True),
        sa.Column("external_account_ref", sa.String(255), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="unknown"),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_top_up_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", name="uq_provider_funding_accounts_provider"),
    )
    op.create_index("ix_provider_funding_accounts_provider", "provider_funding_accounts", ["provider"])
    op.create_index("ix_provider_funding_accounts_status", "provider_funding_accounts", ["status"])

    op.create_table(
        "provider_funding_events",
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("amount", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("balance_after", sa.Numeric(18, 6), nullable=True),
        sa.Column("request_id", sa.String(128), nullable=True),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["provider_funding_accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_provider_funding_events_idempotency_key"),
        sa.UniqueConstraint("provider", "request_id", "event_type", name="uq_provider_funding_request_event"),
    )
    for column in ("account_id", "provider", "event_type", "status", "request_id"):
        op.create_index(f"ix_provider_funding_events_{column}", "provider_funding_events", [column])


def downgrade() -> None:
    op.drop_table("provider_funding_events")
    op.drop_table("provider_funding_accounts")
