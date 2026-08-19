"""harden billing reservation expiry and ledger immutability

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("pricing_rules", "price_per_unit", type_=sa.Numeric(18, 12), existing_type=sa.Numeric(12, 6), existing_nullable=False)
    op.alter_column("pricing_rules", "cached_price_per_unit", type_=sa.Numeric(18, 12), existing_type=sa.Numeric(12, 6), existing_nullable=True)
    op.add_column(
        "billing_reservations",
        sa.Column("resource_type", sa.String(64), nullable=False, server_default="metered_operation"),
    )
    op.add_column(
        "billing_reservations",
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now() + interval '15 minutes'"),
        ),
    )
    op.create_index("ix_billing_reservations_expires_at", "billing_reservations", ["expires_at"])
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_billing_ledger_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'billing_ledger is immutable; append a reversal or adjustment instead';
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER billing_ledger_immutable
        BEFORE UPDATE OR DELETE ON billing_ledger
        FOR EACH ROW EXECUTE FUNCTION prevent_billing_ledger_mutation();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS billing_ledger_immutable ON billing_ledger")
    op.execute("DROP FUNCTION IF EXISTS prevent_billing_ledger_mutation()")
    op.drop_index("ix_billing_reservations_expires_at", table_name="billing_reservations")
    op.drop_column("billing_reservations", "expires_at")
    op.drop_column("billing_reservations", "resource_type")
    op.alter_column("pricing_rules", "cached_price_per_unit", type_=sa.Numeric(12, 6), existing_type=sa.Numeric(18, 12), existing_nullable=True)
    op.alter_column("pricing_rules", "price_per_unit", type_=sa.Numeric(12, 6), existing_type=sa.Numeric(18, 12), existing_nullable=False)
