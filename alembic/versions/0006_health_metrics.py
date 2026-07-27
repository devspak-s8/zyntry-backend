"""Add health metrics tables.

Revision ID: 0006_health_metrics
Revises: 0005_memory_expansion
Create Date: 2026-07-24 10:44:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0006_health_metrics"
down_revision: str | None = "0005_memory_expansion"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "health_metrics",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("runtime_id", sa.UUID(), nullable=False),
        sa.Column("metric_type", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["runtime_id"], ["runtimes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_health_metrics_runtime_type", "health_metrics", ["runtime_id", "metric_type"])
    op.create_index("ix_health_metrics_runtime_created", "health_metrics", ["runtime_id", "created_at"])

    op.create_table(
        "runtime_health_checks",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("runtime_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("health_score", sa.Float(), default=0.0, nullable=False),
        sa.Column("embedding_latency_ms", sa.Float(), nullable=True),
        sa.Column("retrieval_latency_ms", sa.Float(), nullable=True),
        sa.Column("llm_latency_ms", sa.Float(), nullable=True),
        sa.Column("token_usage", sa.Integer(), default=0, nullable=False),
        sa.Column("storage_usage", sa.Integer(), default=0, nullable=False),
        sa.Column("index_size", sa.Integer(), default=0, nullable=False),
        sa.Column("memory_usage_mb", sa.Float(), nullable=True),
        sa.Column("worker_queue_depth", sa.Integer(), default=0, nullable=False),
        sa.Column("last_sync_success", sa.String(length=32), nullable=True),
        sa.Column("last_propagation_success", sa.String(length=32), nullable=True),
        sa.Column("error_count", sa.Integer(), default=0, nullable=False),
        sa.Column("cache_hit_rate", sa.Float(), nullable=True),
        sa.Column("retrieval_quality", sa.Float(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["runtime_id"], ["runtimes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_runtime_health_checks_runtime", "runtime_health_checks", ["runtime_id"])
    op.create_index("ix_runtime_health_checks_runtime_created", "runtime_health_checks", ["runtime_id", "created_at"])


def downgrade() -> None:
    op.drop_table("runtime_health_checks")
    op.drop_table("health_metrics")