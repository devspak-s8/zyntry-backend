"""add OAuth connection context to states

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("oauth_states", sa.Column("purpose", sa.String(16), nullable=False, server_default="tool"))
    op.add_column("oauth_states", sa.Column("display_name", sa.String(255)))
    op.add_column("oauth_states", sa.Column("source_config", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")))


def downgrade() -> None:
    op.drop_column("oauth_states", "source_config")
    op.drop_column("oauth_states", "display_name")
    op.drop_column("oauth_states", "purpose")
