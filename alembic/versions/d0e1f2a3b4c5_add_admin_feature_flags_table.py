"""create the admin feature flag table when migrations own the schema

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4

The table was historically created by ``Base.metadata.create_all``.  That is
not run in production anymore, so fresh and existing migration-managed
databases need an explicit table definition for feature-flag seeding.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "d0e1f2a3b4c5"
down_revision: Union[str, None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_feature_flags (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            key VARCHAR NOT NULL UNIQUE,
            name VARCHAR NOT NULL,
            description TEXT,
            scope VARCHAR NOT NULL,
            flag_type VARCHAR NOT NULL,
            enabled BOOLEAN NOT NULL DEFAULT FALSE,
            default_value BOOLEAN,
            rollout_percentage INTEGER NOT NULL DEFAULT 100,
            allowlist JSONB,
            is_system BOOLEAN NOT NULL DEFAULT FALSE,
            updated_by UUID
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS admin_feature_flags")
