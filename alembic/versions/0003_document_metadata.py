"""Add document intelligence columns.

Revision ID: 0003_document_metadata
Revises: 0002_runtimes
Create Date: 2026-07-24 09:33:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0003_document_metadata"
down_revision: str | None = "0002_runtimes"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("author", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column(
            "metadata",
            sa.JSON(),
            server_default=sa.text("'{}'::json"),
            nullable=False,
        ),
    )
    op.add_column(
        "documents",
        sa.Column("language", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("version", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("content_hash", sa.String(length=64), nullable=True),
    )
    op.create_index("ix_documents_author", "documents", ["author"], unique=False)
    op.create_index("ix_documents_language", "documents", ["language"], unique=False)
    op.create_index("ix_documents_hash", "documents", ["hash"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_documents_hash", table_name="documents")
    op.drop_index("ix_documents_language", table_name="documents")
    op.drop_index("ix_documents_author", table_name="documents")
    op.drop_column("documents", "content_hash")
    op.drop_column("documents", "version")
    op.drop_column("documents", "hash")
    op.drop_column("documents", "language")
    op.drop_column("documents", "metadata")
    op.drop_column("documents", "author")
