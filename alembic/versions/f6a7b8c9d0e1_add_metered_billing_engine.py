"""add metered billing engine

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("wallets", sa.Column("reserved_balance", sa.Numeric(12, 4), nullable=False, server_default="0"))
    op.add_column("wallets", sa.Column("total_spent", sa.Numeric(12, 4), nullable=False, server_default="0"))
    op.add_column("wallets", sa.Column("total_topups", sa.Numeric(12, 4), nullable=False, server_default="0"))

    for name, typ in (
        ("cached_price_per_unit", sa.Numeric(12, 6)),
        ("markup", sa.Numeric(8, 4)),
        ("effective_from", sa.DateTime(timezone=True)),
        ("effective_until", sa.DateTime(timezone=True)),
        ("version", sa.Integer()),
    ):
        kwargs = {"nullable": True}
        if name == "markup":
            kwargs = {"nullable": False, "server_default": "0"}
        if name == "effective_from":
            kwargs = {"nullable": False, "server_default": sa.text("now()")}
        if name == "version":
            kwargs = {"nullable": False, "server_default": "1"}
        op.add_column("pricing_rules", sa.Column(name, typ, **kwargs))

    usage_columns = [
        ("organization_id", sa.Uuid()),
        ("api_key_id", sa.Uuid()),
        ("request_id", sa.String(128)),
        ("cached_tokens", sa.Integer()),
        ("provider_cost", sa.Numeric(12, 4)),
        ("platform_markup", sa.Numeric(12, 4)),
    ]
    for name, typ in usage_columns:
        default = "0" if name in {"cached_tokens", "provider_cost", "platform_markup"} else None
        op.add_column("usage_logs", sa.Column(name, typ, nullable=False if default is not None else True, server_default=default))
    for name in ("organization_id", "api_key_id", "request_id"):
        op.create_index(f"ix_usage_logs_{name}", "usage_logs", [name])

    op.create_table(
        "billing_ledger",
        sa.Column("transaction_type", sa.String(32), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("runtime_id", sa.Uuid(), nullable=True),
        sa.Column("api_key_id", sa.Uuid(), nullable=True),
        sa.Column("request_id", sa.String(128), nullable=True),
        sa.Column("idempotency_key", sa.String(255), nullable=True),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.String(255), nullable=True),
        sa.Column("amount", sa.Numeric(12, 4), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="usd"),
        sa.Column("provider_cost", sa.Numeric(12, 4), nullable=False, server_default="0"),
        sa.Column("platform_markup", sa.Numeric(12, 4), nullable=False, server_default="0"),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_billing_ledger_idempotency_key"),
    )
    for col in ("transaction_type", "user_id", "organization_id", "project_id", "runtime_id", "api_key_id", "request_id", "status"):
        op.create_index(f"ix_billing_ledger_{col}", "billing_ledger", [col])

    op.create_table(
        "billing_reservations",
        sa.Column("wallet_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("runtime_id", sa.Uuid(), nullable=True),
        sa.Column("api_key_id", sa.Uuid(), nullable=True),
        sa.Column("request_id", sa.String(128), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("estimated_amount", sa.Numeric(12, 4), nullable=False),
        sa.Column("settled_amount", sa.Numeric(12, 4), nullable=True),
        sa.Column("released_amount", sa.Numeric(12, 4), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="usd"),
        sa.Column("status", sa.String(16), nullable=False, server_default="reserved"),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["wallet_id"], ["wallets.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("idempotency_key", name="uq_billing_reservations_idempotency_key"),
    )
    for col in ("wallet_id", "user_id", "organization_id", "project_id", "runtime_id", "api_key_id", "request_id", "status"):
        op.create_index(f"ix_billing_reservations_{col}", "billing_reservations", [col])

    op.create_table(
        "spending_limits",
        sa.Column("scope_type", sa.String(16), nullable=False),
        sa.Column("scope_id", sa.Uuid(), nullable=False),
        sa.Column("period", sa.String(16), nullable=False),
        sa.Column("amount", sa.Numeric(12, 4), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scope_type", "scope_id", "period", name="uq_spending_limit_scope_period"),
    )
    op.create_index("ix_spending_limits_scope_type", "spending_limits", ["scope_type"])
    op.create_index("ix_spending_limits_scope_id", "spending_limits", ["scope_id"])
    op.create_index("ix_spending_limits_period", "spending_limits", ["period"])


def downgrade() -> None:
    op.drop_table("spending_limits")
    op.drop_table("billing_reservations")
    op.drop_table("billing_ledger")
    for name in ("organization_id", "api_key_id", "request_id"):
        op.drop_index(f"ix_usage_logs_{name}", table_name="usage_logs")
    for name, _ in (
        ("organization_id", None), ("api_key_id", None), ("request_id", None),
        ("cached_tokens", None), ("provider_cost", None), ("platform_markup", None),
    ):
        op.drop_column("usage_logs", name)
    for name in ("cached_price_per_unit", "markup", "effective_from", "effective_until", "version"):
        op.drop_column("pricing_rules", name)
    for name in ("reserved_balance", "total_spent", "total_topups"):
        op.drop_column("wallets", name)
