"""Add user_id to api_keys table.

Revision ID: 0013_api_key_user
Revises: 0012_user_two_factor
Create Date: 2026-08-03 07:28:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision: str = "0013_api_key_user"
down_revision: str | None = "0012_user_two_factor"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "api_keys",
        sa.Column("user_id", sa.UUID(), nullable=True),
    )
    op.create_index("ix_api_keys_user_id", "api_keys", ["user_id"])
    op.create_foreign_key("fk_api_keys_user_id", "api_keys", "users", ["user_id"], ["id"], ondelete="CASCADE")


def downgrade() -> None:
    op.drop_constraint("fk_api_keys_user_id", "api_keys", type_="foreignkey")
    op.drop_index("ix_api_keys_user_id", table_name="api_keys")
    op.drop_column("api_keys", "user_id")
