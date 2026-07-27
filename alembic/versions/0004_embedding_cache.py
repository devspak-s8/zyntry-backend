"""Add embedding cache table.

Revision ID: 0004_embedding_cache
Revises: 0003_document_metadata
Create Date: 2026-07-24 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0004_embedding_cache"
down_revision: str | None = "0003_document_metadata"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "embedding_caches",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column("embedding_version", sa.String(length=32), nullable=False),
        sa.Column("embedding_model", sa.String(length=128), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("vector", sa.JSON(), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_embedding_caches_project_content_version", "embedding_caches", ["project_id", "content_hash", "embedding_version"], unique=False)
    op.create_index("ix_embedding_caches_lookup", "embedding_caches", ["project_id", "content_hash", "embedding_version", "embedding_model", "provider"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_embedding_caches_lookup", table_name="embedding_caches")
    op.drop_index("ix_embedding_caches_project_content_version", table_name="embedding_caches")
    op.drop_table("embedding_caches")
