from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import uuid

import pytest

from app.services.runtime_assistant.optimizer import RuntimeOptimizer


@pytest.mark.asyncio
async def test_cost_optimizer_accepts_dictionary_model_breakdown() -> None:
    optimizer = RuntimeOptimizer(
        SimpleNamespace(session=object()), str(uuid.uuid4()), str(uuid.uuid4())
    )
    summary = {
        "total_cost": 60,
        "by_model": {"gpt-4o": 35.0, "gpt-4o-mini": 25.0},
    }
    with patch(
        "app.services.billing.BillingService.get_usage_summary",
        new=AsyncMock(return_value=summary),
    ):
        results = await optimizer.optimize_cost()
    assert any("gpt-4o" in result.title for result in results)
