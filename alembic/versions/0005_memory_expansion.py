"""Expand memory_records with intelligence fields.

Revision ID: 0005_memory_expansion
Revises: 0004_embedding_cache
Create Date: 2026-07-24 10:21:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0005_memory_expansion"
down_revision: str | None = "0004_embedding_cache"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "memory_records",
        sa.Column("memory_type", sa.String(length=32), server_default="long_term", nullable=False),
    )
    op.add_column("memory_records", sa.Column("conversation_id", sa.UUID(), nullable=True))
    op.add_column("memory_records", sa.Column("session_id", sa.String(length=64), nullable=True))
    op.add_column(
        "memory_records",
        sa.Column("pinned", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("memory_records", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("memory_records", sa.Column("parent_key", sa.String(length=255), nullable=True))
    op.create_index("ix_memory_records_project_type", "memory_records", ["project_id", "memory_type"])
    op.create_index("ix_memory_records_conversation", "memory_records", ["conversation_id"])
    op.create_index("ix_memory_records_session", "memory_records", ["session_id"])
    op.create_index("ix_memory_records_parent_key", "memory_records", ["parent_key"])
    op.create_index("ix_memory_records_expires_at", "memory_records", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_memory_records_expires_at", table_name="memory_records")
    op.drop_index("ix_memory_records_parent_key", table_name="memory_records")
    op.drop_index("ix_memory_records_session", table_name="memory_records")
    op.drop_index("ix_memory_records_conversation", table_name="memory_records")
    op.drop_index("ix_memory_records_project_type", table_name="memory_records")
    op.drop_column("memory_records", "parent_key")
    op.drop_column("memory_records", "expires_at")
    op.drop_column("memory_records", "pinned")
    op.drop_column("memory_records", "session_id")
    op.drop_column("memory_records", "conversation_id")
    op.drop_column("memory_records", "memory_type")
