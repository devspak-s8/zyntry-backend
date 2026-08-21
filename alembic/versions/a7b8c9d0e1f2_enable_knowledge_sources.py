"""enable website and external knowledge sources

Revision ID: a7b8c9d0e1f3
Revises: a7b8c9d0e1f2
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7b8c9d0e1f3"
down_revision: Union[str, None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Knowledge sources are now part of the supported project setup flow.
    op.execute(
        sa.text(
            "UPDATE feature_flags "
            "SET enabled = TRUE, default_value = TRUE, rollout_percentage = 100 "
            "WHERE key = 'knowledge_sources'"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE feature_flags "
            "SET enabled = TRUE, default_value = FALSE, rollout_percentage = 0 "
            "WHERE key = 'knowledge_sources'"
        )
    )
