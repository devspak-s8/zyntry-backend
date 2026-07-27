"""Billing system: wallets, transactions, pricing, usage logs, and budgets.

Revision ID: 0008_billing_system
Revises: 0007_apikey_expansion
Create Date: 2026-07-25 10:16:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008_billing_system"
down_revision: str | None = "0007_apikey_expansion"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "wallets",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("balance", sa.Numeric(12, 4), server_default="0.0000", nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="usd", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_wallets"),
        sa.UniqueConstraint("user_id", name="uq_wallets_user_id"),
    )
    op.create_index("ix_wallets_user_id", "wallets", ["user_id"], unique=False)

    op.create_table(
        "wallet_transactions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("wallet_id", sa.UUID(), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("amount", sa.Numeric(12, 4), nullable=False),
        sa.Column("balance_before", sa.Numeric(12, 4), nullable=False),
        sa.Column("balance_after", sa.Numeric(12, 4), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("reference_id", sa.String(length=255), nullable=True),
        sa.Column("metadata", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["wallet_id"], ["wallets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_wallet_transactions"),
    )
    op.create_index("ix_wallet_transactions_wallet_id", "wallet_transactions", ["wallet_id"], unique=False)
    op.create_index("ix_wallet_transactions_reference_id", "wallet_transactions", ["reference_id"], unique=False)
    op.create_index("ix_wallet_transactions_type", "wallet_transactions", ["type"], unique=False)

    op.create_table(
        "pricing_rules",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column("price_per_unit", sa.Numeric(12, 6), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="usd", nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_pricing_rules"),
    )
    op.create_index("ix_pricing_rules_provider", "pricing_rules", ["provider"], unique=False)
    op.create_index("ix_pricing_rules_operation", "pricing_rules", ["operation"], unique=False)
    op.create_index("ix_pricing_rules_model", "pricing_rules", ["model"], unique=False)
    op.create_index("ix_pricing_rules_active", "pricing_rules", ["active"], unique=False)
    op.create_index(
        "ix_pricing_rules_provider_operation_model",
        "pricing_rules",
        ["provider", "operation", "model"],
        unique=False,
    )

    op.create_table(
        "usage_logs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("runtime_id", sa.UUID(), nullable=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("input_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("embedding_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("vector_searches", sa.Integer(), server_default="0", nullable=False),
        sa.Column("storage_bytes", sa.Integer(), server_default="0", nullable=False),
        sa.Column("requests", sa.Integer(), server_default="1", nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("cost", sa.Numeric(12, 4), server_default="0.0000", nullable=False),
        sa.Column("metadata", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_usage_logs"),
    )
    op.create_index("ix_usage_logs_user_id", "usage_logs", ["user_id"], unique=False)
    op.create_index("ix_usage_logs_project_id", "usage_logs", ["project_id"], unique=False)
    op.create_index("ix_usage_logs_runtime_id", "usage_logs", ["runtime_id"], unique=False)
    op.create_index("ix_usage_logs_provider", "usage_logs", ["provider"], unique=False)
    op.create_index("ix_usage_logs_model", "usage_logs", ["model"], unique=False)
    op.create_index("ix_usage_logs_operation", "usage_logs", ["operation"], unique=False)
    op.create_index("ix_usage_logs_created_at", "usage_logs", ["created_at"], unique=False)

    op.create_table(
        "budgets",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("monthly_limit", sa.Numeric(12, 4), nullable=True),
        sa.Column("current_spend", sa.Numeric(12, 4), server_default="0.0000", nullable=False),
        sa.Column("warning_80_sent", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("warning_90_sent", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("limit_reached", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("auto_top_up_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("auto_top_up_threshold", sa.Numeric(12, 4), nullable=True),
        sa.Column("auto_top_up_amount", sa.Numeric(12, 4), nullable=True),
        sa.Column("auto_top_up_stripe_payment_method_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_budgets"),
        sa.UniqueConstraint("user_id", name="uq_budgets_user_id"),
    )
    op.create_index("ix_budgets_user_id", "budgets", ["user_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_budgets_user_id", table_name="budgets")
    op.drop_table("budgets")
    op.drop_index("ix_usage_logs_created_at", table_name="usage_logs")
    op.drop_index("ix_usage_logs_operation", table_name="usage_logs")
    op.drop_index("ix_usage_logs_model", table_name="usage_logs")
    op.drop_index("ix_usage_logs_provider", table_name="usage_logs")
    op.drop_index("ix_usage_logs_runtime_id", table_name="usage_logs")
    op.drop_index("ix_usage_logs_project_id", table_name="usage_logs")
    op.drop_index("ix_usage_logs_user_id", table_name="usage_logs")
    op.drop_table("usage_logs")
    op.drop_index("ix_pricing_rules_provider_operation_model", table_name="pricing_rules")
    op.drop_index("ix_pricing_rules_active", table_name="pricing_rules")
    op.drop_index("ix_pricing_rules_model", table_name="pricing_rules")
    op.drop_index("ix_pricing_rules_operation", table_name="pricing_rules")
    op.drop_index("ix_pricing_rules_provider", table_name="pricing_rules")
    op.drop_table("pricing_rules")
    op.drop_index("ix_wallet_transactions_type", table_name="wallet_transactions")
    op.drop_index("ix_wallet_transactions_reference_id", table_name="wallet_transactions")
    op.drop_index("ix_wallet_transactions_wallet_id", table_name="wallet_transactions")
    op.drop_table("wallet_transactions")
    op.drop_index("ix_wallets_user_id", table_name="wallets")
    op.drop_table("wallets")
