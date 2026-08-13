from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.billing import BillingService


@pytest.mark.asyncio
async def test_record_usage_creates_and_publishes_analytics_event() -> None:
    event = SimpleNamespace(
        id=uuid.uuid4(), metric="runtime_invocation", quantity=15,
        created_at=SimpleNamespace(isoformat=lambda: "2026-08-13T00:00:00+00:00"),
    )
    uow = SimpleNamespace(
        usage_logs=SimpleNamespace(create=AsyncMock(return_value=SimpleNamespace())),
        analytics=SimpleNamespace(create=AsyncMock(return_value=event)),
        commit=AsyncMock(),
    )
    service = BillingService.__new__(BillingService)
    service.uow = uow
    project_id = uuid.uuid4()
    runtime_id = uuid.uuid4()

    with patch("app.core.runtime_events.publish_runtime_event", new=AsyncMock()) as publish:
        await service.record_usage(
            user_id=uuid.uuid4(), provider="openai", model="gpt-4o-mini",
            operation="invoke", cost=Decimal("0.001"), project_id=project_id,
            runtime_id=runtime_id, input_tokens=10, output_tokens=5, latency_ms=120,
        )

    assert uow.analytics.create.await_args.kwargs["quantity"] == 15
    event_payload = publish.await_args.args[0]
    assert event_payload["type"] == "analytics.usage.updated"
    assert event_payload["project_id"] == str(project_id)
