"""Add two_factor columns to users table.

Revision ID: 0012_user_two_factor
Revises: 0011_provider_connections_onboarding
Create Date: 2026-08-02 21:05:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision: str = "0012_user_two_factor"
down_revision: str | None = "0011_provider_connections_onboarding"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("two_factor_enabled", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "users",
        sa.Column("two_factor_secret", sa.String(255), nullable=True),
    )
    op.alter_column("users", "two_factor_enabled", server_default=None)


def downgrade() -> None:
    op.drop_column("users", "two_factor_secret")
    op.drop_column("users", "two_factor_enabled")
