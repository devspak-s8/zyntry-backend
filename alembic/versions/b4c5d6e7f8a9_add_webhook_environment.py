"""scope webhook subscriptions to project environments

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b4c5d6e7f8a9"
down_revision: str | None = "a3b4c5d6e7f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE webhook_subscriptions ADD COLUMN IF NOT EXISTS environment VARCHAR(32) NOT NULL DEFAULT 'development'"
    )
    op.execute("ALTER TABLE webhook_subscriptions ALTER COLUMN secret TYPE VARCHAR(512)")


def downgrade() -> None:
    op.execute("ALTER TABLE webhook_subscriptions ALTER COLUMN secret TYPE VARCHAR(255)")
    op.execute("ALTER TABLE webhook_subscriptions DROP COLUMN IF EXISTS environment")
