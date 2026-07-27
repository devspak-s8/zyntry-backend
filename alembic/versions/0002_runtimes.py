"""Add runtime tables.

Revision ID: 0002_runtimes
Revises: 0001_initial
Create Date: 2025-01-24 08:04:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0002_runtimes"
down_revision: str | None = "0001_initial"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "runtimes",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("embedding_model", sa.String(length=128), nullable=False),
        sa.Column("vector_store", sa.String(length=64), nullable=False),
        sa.Column("chunk_size", sa.Integer(), nullable=False),
        sa.Column("chunk_overlap", sa.Integer(), nullable=False),
        sa.Column("documents", sa.Integer(), nullable=False),
        sa.Column("chunks", sa.Integer(), nullable=False),
        sa.Column("embeddings", sa.Integer(), nullable=False),
        sa.Column("index_size", sa.Integer(), nullable=False),
        sa.Column("last_build_started", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_build_completed", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_propagated", sa.DateTime(timezone=True), nullable=True),
        sa.Column("health", sa.Float(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("api_key_id", sa.UUID(), nullable=True),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["api_key_id"], ["api_keys.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id"),
    )
    op.create_index("ix_runtimes_project_id", "runtimes", ["project_id"], unique=False)
    op.create_index("ix_runtimes_organization_id", "runtimes", ["organization_id"], unique=False)
    op.create_index("ix_runtimes_status", "runtimes", ["status"], unique=False)

    op.create_table(
        "runtime_build_logs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("runtime_id", sa.UUID(), nullable=False),
        sa.Column("stage", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["runtime_id"], ["runtimes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_runtime_build_logs_runtime_id", "runtime_build_logs", ["runtime_id"], unique=False)
    op.create_index("ix_runtime_build_logs_stage", "runtime_build_logs", ["stage"], unique=False)

    op.create_table(
        "runtime_build_chunks",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("runtime_id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("embedded", sa.Boolean(), nullable=False),
        sa.Column("indexed", sa.Boolean(), nullable=False),
        sa.Column("embedding_hash", sa.String(length=128), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["runtime_id"], ["runtimes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_runtime_build_chunks_runtime_id", "runtime_build_chunks", ["runtime_id"], unique=False)
    op.create_index("ix_runtime_build_chunks_document_id", "runtime_build_chunks", ["document_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_runtime_build_chunks_document_id", table_name="runtime_build_chunks")
    op.drop_index("ix_runtime_build_chunks_runtime_id", table_name="runtime_build_chunks")
    op.drop_table("runtime_build_chunks")
    op.drop_index("ix_runtime_build_logs_stage", table_name="runtime_build_logs")
    op.drop_index("ix_runtime_build_logs_runtime_id", table_name="runtime_build_logs")
    op.drop_table("runtime_build_logs")
    op.drop_index("ix_runtimes_status", table_name="runtimes")
    op.drop_index("ix_runtimes_organization_id", table_name="runtimes")
    op.drop_index("ix_runtimes_project_id", table_name="runtimes")
    op.drop_table("runtimes")
