"""add onboarding sessions, runtime integrations, and integration connections

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Update runtimes table
    op.add_column("runtimes", sa.Column("name", sa.String(255), nullable=False, server_default="Default Runtime"))
    op.add_column("runtimes", sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True))
    op.add_column("runtimes", sa.Column("environment", sa.String(32), nullable=False, server_default="development"))
    op.add_column("runtimes", sa.Column("routing_strategy", sa.String(64), nullable=False, server_default="balanced"))
    op.add_column("runtimes", sa.Column("fallback_models", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column("runtimes", sa.Column("security_policies", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.add_column("runtimes", sa.Column("system_instructions", sa.Text(), nullable=True))

    op.alter_column("runtimes", "project_id", nullable=True)
    op.alter_column("runtimes", "organization_id", nullable=True)

    # 2. Update api_keys table
    op.add_column("api_keys", sa.Column("runtime_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("runtimes.id", ondelete="CASCADE"), nullable=True))
    op.add_column("api_keys", sa.Column("environment", sa.String(32), nullable=False, server_default="development"))
    op.alter_column("api_keys", "organization_id", nullable=True)

    # 3. Create integration_connections table
    op.create_table(
        "integration_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("runtime_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("runtimes.id", ondelete="CASCADE"), nullable=True),
        sa.Column("integration_slug", sa.String(64), nullable=False),
        sa.Column("connection_mode", sa.String(64), nullable=False, server_default="zyntry_managed"),
        sa.Column("end_user_id", sa.String(255), nullable=True),
        sa.Column("display_name", sa.String(255), nullable=False, server_default=""),
        sa.Column("auth_method", sa.String(64), nullable=False, server_default="oauth2"),
        sa.Column("encrypted_credentials", sa.Text(), nullable=True),
        sa.Column("scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refresh_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("last_synchronized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("health_status", sa.String(32), nullable=False, server_default="healthy"),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_connections_runtime_enduser", "integration_connections", ["runtime_id", "end_user_id"])
    op.create_index("ix_connections_user_slug", "integration_connections", ["user_id", "integration_slug"])

    # 4. Create runtime_integrations table
    op.create_table(
        "runtime_integrations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("runtime_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("runtimes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("integration_slug", sa.String(64), nullable=False),
        sa.Column("connection_mode", sa.String(64), nullable=False, server_default="zyntry_managed"),
        sa.Column("enabled_capabilities", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("connection_required", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("connection_status", sa.String(32), nullable=False, server_default="not_connected"),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("integration_connections.id", ondelete="SET NULL"), nullable=True),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("runtime_id", "integration_slug", name="uq_runtime_integration_slug"),
    )

    # 5. Create onboarding_sessions table
    op.create_table(
        "onboarding_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("state", sa.String(64), nullable=False, server_default="onboarding_started"),
        sa.Column("messages", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("configuration", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_runtime_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("runtimes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_api_key_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("onboarding_sessions")
    op.drop_table("runtime_integrations")
    op.drop_table("integration_connections")
    op.drop_column("api_keys", "environment")
    op.drop_column("api_keys", "runtime_id")
    op.drop_column("runtimes", "system_instructions")
    op.drop_column("runtimes", "security_policies")
    op.drop_column("runtimes", "fallback_models")
    op.drop_column("runtimes", "routing_strategy")
    op.drop_column("runtimes", "environment")
    op.drop_column("runtimes", "user_id")
    op.drop_column("runtimes", "name")
