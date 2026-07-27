"""Seed initial pricing rules for all supported providers and operations.

Revision ID: 0009_seed_pricing
Revises: 0008_billing_system
Create Date: 2026-07-25 12:00:00.000000
"""

from decimal import Decimal
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_seed_pricing"
down_revision: str | None = "0008_billing_system"
branch_labels: str | None = None
depends_on: str | None = None


pricing_rules = [
    ("openai", "input_tokens", None, "tokens", Decimal("0.000015"), "usd"),
    ("openai", "output_tokens", None, "tokens", Decimal("0.000060"), "usd"),
    ("openai", "embeddings", None, "tokens", Decimal("0.000020"), "usd"),
    ("openai", "image_generation", "dall-e-3", "image", Decimal("0.040000"), "usd"),
    ("openai", "image_generation", "dall-e-2", "image", Decimal("0.020000"), "usd"),
    ("anthropic", "input_tokens", None, "tokens", Decimal("0.000008"), "usd"),
    ("anthropic", "output_tokens", None, "tokens", Decimal("0.000024"), "usd"),
    ("anthropic", "embeddings", None, "tokens", Decimal("0.000020"), "usd"),
    ("gemini", "input_tokens", None, "tokens", Decimal("0.00000125"), "usd"),
    ("gemini", "output_tokens", None, "tokens", Decimal("0.00000500"), "usd"),
    ("gemini", "embeddings", None, "tokens", Decimal("0.000020"), "usd"),
    ("groq", "input_tokens", None, "tokens", Decimal("0.000001"), "usd"),
    ("groq", "output_tokens", None, "tokens", Decimal("0.000002"), "usd"),
    ("deepseek", "input_tokens", None, "tokens", Decimal("0.00000014"), "usd"),
    ("deepseek", "output_tokens", None, "tokens", Decimal("0.00000028"), "usd"),
    ("mistral", "input_tokens", None, "tokens", Decimal("0.000004"), "usd"),
    ("mistral", "output_tokens", None, "tokens", Decimal("0.000012"), "usd"),
    ("openrouter", "input_tokens", None, "tokens", Decimal("0.000001"), "usd"),
    ("openrouter", "output_tokens", None, "tokens", Decimal("0.000002"), "usd"),
    ("voyage", "embeddings", None, "tokens", Decimal("0.000020"), "usd"),
    ("cohere", "embeddings", None, "tokens", Decimal("0.000015"), "usd"),
    ("cohere", "input_tokens", None, "tokens", Decimal("0.000004"), "usd"),
    ("cohere", "output_tokens", None, "tokens", Decimal("0.000008"), "usd"),
    ("fireworks", "input_tokens", None, "tokens", Decimal("0.000002"), "usd"),
    ("fireworks", "output_tokens", None, "tokens", Decimal("0.000006"), "usd"),
    ("azure_openai", "input_tokens", None, "tokens", Decimal("0.000015"), "usd"),
    ("azure_openai", "output_tokens", None, "tokens", Decimal("0.000060"), "usd"),
    ("azure_openai", "embeddings", None, "tokens", Decimal("0.000020"), "usd"),
    ("bedrock", "input_tokens", None, "tokens", Decimal("0.000015"), "usd"),
    ("bedrock", "output_tokens", None, "tokens", Decimal("0.000060"), "usd"),
    ("bedrock", "embeddings", None, "tokens", Decimal("0.000020"), "usd"),
    ("openai", "vector_search", None, "search", Decimal("0.000100"), "usd"),
    ("anthropic", "vector_search", None, "search", Decimal("0.000100"), "usd"),
    ("openai", "storage", None, "bytes", Decimal("0.00000001"), "usd"),
    ("openai", "web_search", None, "request", Decimal("0.005000"), "usd"),
]


def upgrade() -> None:
    pricing_rules_table = sa.table(
        "pricing_rules",
        sa.column("provider", sa.String(64)),
        sa.column("operation", sa.String(64)),
        sa.column("model", sa.String(128)),
        sa.column("unit", sa.String(32)),
        sa.column("price_per_unit", sa.Numeric(12, 6)),
        sa.column("currency", sa.String(3)),
        sa.column("active", sa.Boolean()),
    )

    op.bulk_insert(
        pricing_rules_table,
        [
            {
                "provider": provider,
                "operation": operation,
                "model": model,
                "unit": unit,
                "price_per_unit": float(price),
                "currency": currency,
                "active": True,
            }
            for provider, operation, model, unit, price, currency in pricing_rules
        ],
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM pricing_rules"))
