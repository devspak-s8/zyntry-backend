"""add environment origin restrictions to api keys

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a3b4c5d6e7f8"
down_revision: str | None = "f2a3b4c5d6e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS allowed_origins JSON NOT NULL DEFAULT '[]'::json"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE api_keys DROP COLUMN IF EXISTS allowed_origins")
