"""create OAuth provider, connection, and state tables

Revision ID: a2b3c4d5e6f7
Revises: a1b2c3d4e5f6

The original baseline migration omitted the OAuth tables even though the
application models and repositories depend on them.  Keep the DDL idempotent
so deployments that created the tables through ``create_all`` can migrate
without errors.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "a2b3c4d5e6f7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS oauth_providers (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR(64) NOT NULL UNIQUE,
            display_name VARCHAR(255) NOT NULL,
            client_id VARCHAR(255) NOT NULL,
            client_secret_encrypted TEXT NOT NULL,
            auth_url VARCHAR(512) NOT NULL,
            token_url VARCHAR(512) NOT NULL,
            scopes JSON NOT NULL DEFAULT '[]'::json,
            is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS oauth_connections (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL,
            project_id UUID NOT NULL,
            provider_id UUID NOT NULL,
            access_token_encrypted TEXT NOT NULL,
            refresh_token_encrypted TEXT,
            expires_at TIMESTAMPTZ,
            scope VARCHAR(512),
            status VARCHAR(32) NOT NULL DEFAULT 'active',
            metadata JSON NOT NULL DEFAULT '{}'::json,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS oauth_states (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            provider VARCHAR(64) NOT NULL,
            state VARCHAR(128) NOT NULL UNIQUE,
            code_verifier VARCHAR(255),
            user_id UUID,
            project_id UUID,
            redirect_uri VARCHAR(512),
            expires_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS oauth_states")
    op.execute("DROP TABLE IF EXISTS oauth_connections")
    op.execute("DROP TABLE IF EXISTS oauth_providers")
