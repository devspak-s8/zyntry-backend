"""add OAuth connection context to states

Revision ID: b2c3d4e5f6a7
Revises: a2b3c4d5e6f7
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Use IF NOT EXISTS for compatibility with databases that already had the
    # columns created by the application's historical ``create_all`` startup.
    op.execute(
        "ALTER TABLE oauth_states ADD COLUMN IF NOT EXISTS purpose VARCHAR(16) NOT NULL DEFAULT 'tool'"
    )
    op.execute(
        "ALTER TABLE oauth_states ADD COLUMN IF NOT EXISTS display_name VARCHAR(255)"
    )
    op.execute(
        "ALTER TABLE oauth_states ADD COLUMN IF NOT EXISTS source_config JSON NOT NULL DEFAULT '{}'::json"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE oauth_states DROP COLUMN IF EXISTS source_config")
    op.execute("ALTER TABLE oauth_states DROP COLUMN IF EXISTS display_name")
    op.execute("ALTER TABLE oauth_states DROP COLUMN IF EXISTS purpose")
