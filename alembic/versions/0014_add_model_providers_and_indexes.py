"""add project provider fk and missing indexes

Revision ID: 0014_add_model_providers_and_indexes
Revises: 0013_api_key_user
Create Date: 2026-08-03 19:47:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0014_add_model_providers_and_indexes"
down_revision: Union[str, None] = "0013_api_key_user"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "model_providers",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE", name="fk_model_providers_project_id"),
        sa.PrimaryKeyConstraint("id", name="pk_model_providers"),
    )
    op.create_index("ix_model_providers_project_id", "model_providers", ["project_id"], unique=False)
    op.create_index("ix_projects_organization_id", "projects", ["organization_id"], unique=False)
    op.create_index("ix_projects_org_status", "projects", ["organization_id", "status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_projects_org_status", table_name="projects")
    op.drop_index("ix_projects_organization_id", table_name="projects")
    op.drop_index("ix_model_providers_project_id", table_name="model_providers")
    op.drop_table("model_providers")
