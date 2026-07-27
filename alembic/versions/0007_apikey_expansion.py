"""Expand api_keys with scopes, usage tracking, and usage stats.

Revision ID: 0007_apikey_expansion
Revises: 0006_health_metrics
Create Date: 2026-07-24 11:34:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0007_apikey_expansion"
down_revision: str | None = "0006_scheduler"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "api_keys",
        sa.Column("scopes", sa.JSON(), server_default="[]", nullable=False),
    )
    op.add_column(
        "api_keys",
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "api_keys",
        sa.Column("usage_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "api_keys",
        sa.Column("usage_stats", sa.JSON(), server_default="{}", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("api_keys", "usage_stats")
    op.drop_column("api_keys", "usage_count")
    op.drop_column("api_keys", "last_used_at")
    op.drop_column("api_keys", "scopes")
