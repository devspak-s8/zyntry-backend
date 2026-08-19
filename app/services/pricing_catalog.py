from __future__ import annotations

"""Versioned, server-owned pricing catalogue.

Values are provider cost per token (not per 1K tokens).  A pricing rule's
``markup`` is applied by :class:`PricingService` and historical rules are never
edited; a new version supersedes them instead.
"""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from app.models.billing import PricingRule


DEFAULT_PRICING_CATALOG = (
    {"provider": "openai", "model": "gpt-4o-mini", "operation": "input_tokens", "unit": "token", "price_per_unit": Decimal("0.00000015")},
    {"provider": "openai", "model": "gpt-4o-mini", "operation": "output_tokens", "unit": "token", "price_per_unit": Decimal("0.00000060")},
    {"provider": "openai", "model": "gpt-4o-mini", "operation": "cached_tokens", "unit": "token", "price_per_unit": Decimal("0.000000075")},
    {"provider": "openai", "model": "gpt-4o", "operation": "input_tokens", "unit": "token", "price_per_unit": Decimal("0.000005")},
    {"provider": "openai", "model": "gpt-4o", "operation": "output_tokens", "unit": "token", "price_per_unit": Decimal("0.000015")},
    {"provider": "openai", "model": "gpt-4o", "operation": "cached_tokens", "unit": "token", "price_per_unit": Decimal("0.0000025")},
    {"provider": "openai", "model": "gpt-3.5-turbo", "operation": "input_tokens", "unit": "token", "price_per_unit": Decimal("0.00000050")},
    {"provider": "openai", "model": "gpt-3.5-turbo", "operation": "output_tokens", "unit": "token", "price_per_unit": Decimal("0.00000150")},
    {"provider": "openai", "model": "gpt-3.5-turbo", "operation": "cached_tokens", "unit": "token", "price_per_unit": Decimal("0.00000025")},
    {"provider": "openai", "model": "text-embedding-3-small", "operation": "embeddings", "unit": "token", "price_per_unit": Decimal("0.00000002")},
    {"provider": "*", "model": None, "operation": "vector_search", "unit": "search", "price_per_unit": Decimal("0.000010")},
    {"provider": "*", "model": None, "operation": "reranking", "unit": "item", "price_per_unit": Decimal("0.000020")},
    # Platform-owned resource meters.  These are intentionally versioned in the
    # same catalogue so adding a new billable capability never requires a code
    # deploy or a hard-coded wallet deduction.
    {"provider": "platform", "model": None, "operation": "storage", "unit": "byte", "price_per_unit": Decimal("0.00000001")},
    {"provider": "platform", "model": None, "operation": "ocr", "unit": "page", "price_per_unit": Decimal("0.003000")},
    {"provider": "platform", "model": None, "operation": "speech_to_text", "unit": "minute", "price_per_unit": Decimal("0.006000")},
    {"provider": "platform", "model": None, "operation": "text_to_speech", "unit": "character", "price_per_unit": Decimal("0.000015")},
    {"provider": "platform", "model": None, "operation": "image_generation", "unit": "image", "price_per_unit": Decimal("0.040000")},
    {"provider": "platform", "model": None, "operation": "image_processing", "unit": "image", "price_per_unit": Decimal("0.005000")},
    {"provider": "platform", "model": None, "operation": "web_search", "unit": "search", "price_per_unit": Decimal("0.001000")},
    {"provider": "platform", "model": None, "operation": "compute", "unit": "second", "price_per_unit": Decimal("0.000100")},
    {"provider": "platform", "model": None, "operation": "integration", "unit": "operation", "price_per_unit": Decimal("0.000500")},
    {"provider": "platform", "model": None, "operation": "background_job", "unit": "job", "price_per_unit": Decimal("0.001000")},
)


async def seed_pricing_catalog(session) -> int:
    """Insert missing catalogue entries without changing existing pricing."""
    created = 0
    now = datetime.now(timezone.utc)
    for item in DEFAULT_PRICING_CATALOG:
        provider = item["provider"]
        result = await session.execute(select(PricingRule).where(
            PricingRule.provider == provider,
            PricingRule.operation == item["operation"],
            PricingRule.model == item["model"],
            PricingRule.version == 1,
        ))
        if result.scalar_one_or_none() is not None:
            continue
        session.add(PricingRule(**item, currency="usd", markup=Decimal("0.20"), effective_from=now, version=1, active=True))
        created += 1
    if created:
        await session.commit()
    return created
