"""add first-class runtime assistant conversation and evidence records

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "runtime_assistant_conversations",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("runtime_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("environment", sa.String(32), nullable=False, server_default="production"),
        sa.Column("title", sa.String(255)),
        sa.Column("status", sa.String(24), nullable=False, server_default="active"),
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["runtime_id"], ["runtimes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_runtime_assistant_conversation_scope", "runtime_assistant_conversations", ["organization_id", "project_id", "runtime_id", "user_id"])
    op.create_table(
        "runtime_assistant_messages",
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(24), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("mode", sa.String(24), nullable=False, server_default="observe"),
        sa.Column("confidence", sa.Float()),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["conversation_id"], ["runtime_assistant_conversations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_runtime_assistant_messages_conversation_created", "runtime_assistant_messages", ["conversation_id", "created_at"])
    op.create_table(
        "runtime_assistant_evidence",
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("evidence_type", sa.String(48), nullable=False),
        sa.Column("source", sa.String(128), nullable=False),
        sa.Column("reference_id", sa.String(255)),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("summary", sa.Text()),
        sa.Column("data", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("deep_link", sa.String(512)),
        sa.Column("redacted", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["conversation_id"], ["runtime_assistant_conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["message_id"], ["runtime_assistant_messages.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_runtime_assistant_evidence_message", "runtime_assistant_evidence", ["message_id"])
    op.create_index("ix_runtime_assistant_evidence_reference", "runtime_assistant_evidence", ["reference_id"])


def downgrade() -> None:
    op.drop_table("runtime_assistant_evidence")
    op.drop_table("runtime_assistant_messages")
    op.drop_table("runtime_assistant_conversations")
