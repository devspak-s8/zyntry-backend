"""add runtime attribution and error category to request logs

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f2a3b4c5d6e7"
down_revision: str | None = "e1f2a3b4c5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE request_logs ADD COLUMN IF NOT EXISTS runtime_id UUID")
    op.execute("ALTER TABLE request_logs ADD COLUMN IF NOT EXISTS error_category VARCHAR(64)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_request_logs_runtime_id ON request_logs (runtime_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_request_logs_request_id ON request_logs (request_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_request_logs_error_category ON request_logs (error_category)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_request_logs_error_category")
    op.execute("DROP INDEX IF EXISTS ix_request_logs_request_id")
    op.execute("DROP INDEX IF EXISTS ix_request_logs_runtime_id")
    op.execute("ALTER TABLE request_logs DROP COLUMN IF EXISTS error_category")
    op.execute("ALTER TABLE request_logs DROP COLUMN IF EXISTS runtime_id")
