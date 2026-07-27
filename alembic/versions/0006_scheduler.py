"""Add sync_schedules table and retry fields to sync_jobs.

Revision ID: 0006_scheduler
Revises: 0005_memory_expansion
Create Date: 2026-07-24 10:45:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0006_scheduler"
down_revision: str | None = "0006_health_metrics"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "sync_schedules",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("frequency", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=True),
        sa.Column("options", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["source_id"], ["knowledge_sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sync_schedules_source_id", "sync_schedules", ["source_id"])
    op.create_index("ix_sync_schedules_project_id", "sync_schedules", ["project_id"])
    op.create_index("ix_sync_schedules_next_run_at", "sync_schedules", ["next_run_at"])
    op.create_index("ix_sync_schedules_status", "sync_schedules", ["status"])
    op.add_column("sync_jobs", sa.Column("retry_count", sa.Integer(), nullable=True))
    op.add_column("sync_jobs", sa.Column("retry_after", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("sync_jobs", "retry_after")
    op.drop_column("sync_jobs", "retry_count")
    op.drop_index("ix_sync_schedules_status", table_name="sync_schedules")
    op.drop_index("ix_sync_schedules_next_run_at", table_name="sync_schedules")
    op.drop_index("ix_sync_schedules_project_id", table_name="sync_schedules")
    op.drop_index("ix_sync_schedules_source_id", table_name="sync_schedules")
    op.drop_table("sync_schedules")