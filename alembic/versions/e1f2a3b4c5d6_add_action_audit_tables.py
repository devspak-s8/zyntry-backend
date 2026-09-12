"""persist action execution, confirmation, and audit records

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5

These tables are required by the action guardrails and runtime assistant but
were previously only created by the local ``create_all`` path.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, None] = "d0e1f2a3b4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS action_executions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL,
            project_id UUID NOT NULL,
            provider VARCHAR(64) NOT NULL,
            action VARCHAR(128) NOT NULL,
            arguments JSON NOT NULL DEFAULT '{}'::json,
            result JSON,
            error TEXT,
            status VARCHAR(32) NOT NULL DEFAULT 'pending',
            duration_ms INTEGER,
            tokens_used INTEGER NOT NULL DEFAULT 0,
            cost DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS action_confirmations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL,
            project_id UUID NOT NULL,
            provider VARCHAR(64) NOT NULL,
            action VARCHAR(128) NOT NULL,
            arguments JSON NOT NULL DEFAULT '{}'::json,
            risk VARCHAR(32) NOT NULL DEFAULT 'low',
            status VARCHAR(32) NOT NULL DEFAULT 'pending',
            expires_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS action_audit_logs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL,
            project_id UUID NOT NULL,
            provider VARCHAR(64) NOT NULL,
            action VARCHAR(128) NOT NULL,
            arguments JSON NOT NULL DEFAULT '{}'::json,
            result JSON,
            status VARCHAR(32) NOT NULL,
            duration_ms INTEGER,
            error TEXT,
            tokens_used INTEGER NOT NULL DEFAULT 0,
            cost DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS action_audit_logs")
    op.execute("DROP TABLE IF EXISTS action_confirmations")
    op.execute("DROP TABLE IF EXISTS action_executions")
