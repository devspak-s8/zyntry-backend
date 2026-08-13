"""add native pgvector storage alongside legacy JSON vectors

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
"""
from typing import Sequence, Union

from alembic import op


revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("ALTER TABLE embeddings ADD COLUMN IF NOT EXISTS vector_native vector")
    op.execute(
        """
        UPDATE embeddings
        SET vector_native = vector::text::vector
        WHERE vector_native IS NULL
          AND jsonb_typeof(vector) = 'array'
          AND jsonb_array_length(vector) > 0
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_embeddings_project_id
        ON embeddings (project_id)
        """
    )
    for dimensions in (768, 1024, 1536):
        op.execute(
            f"""
            CREATE INDEX IF NOT EXISTS ix_embeddings_vector_hnsw_{dimensions}
            ON embeddings USING hnsw
                ((vector_native::vector({dimensions})) vector_cosine_ops)
            WHERE dimensions = {dimensions} AND vector_native IS NOT NULL
            """
        )


def downgrade() -> None:
    for dimensions in (768, 1024, 1536):
        op.execute(f"DROP INDEX IF EXISTS ix_embeddings_vector_hnsw_{dimensions}")
    op.execute("DROP INDEX IF EXISTS ix_embeddings_project_id")
    op.execute("ALTER TABLE embeddings DROP COLUMN IF EXISTS vector_native")
