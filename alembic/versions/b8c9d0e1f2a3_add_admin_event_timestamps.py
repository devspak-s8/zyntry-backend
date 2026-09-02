"""add timestamps required by admin timelines

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f3
"""

from __future__ import annotations

from alembic import op


revision = "b8c9d0e1f2a3"
down_revision = "a7b8c9d0e1f3"
branch_labels = None
depends_on = None


TABLES = (
    "admin_users",
    "admin_audit_logs",
    "admin_login_events",
    "admin_events",
    "admin_event_timeline",
)


def upgrade() -> None:
    # Admin tables are created by application metadata on fresh installations,
    # but already exist on deployed installations. IF EXISTS supports both.
    for table in TABLES:
        op.execute(
            f'ALTER TABLE IF EXISTS "{table}" '
            "ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE "
            "NOT NULL DEFAULT CURRENT_TIMESTAMP"
        )


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(
            f'ALTER TABLE IF EXISTS "{table}" '
            "DROP COLUMN IF EXISTS created_at"
        )
