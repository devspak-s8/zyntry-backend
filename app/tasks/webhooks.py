from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from functools import partial

import httpx
import hmac
import hashlib
from celery import shared_task

from app.core.config import settings
from app.core.database import run_async
from app.models.webhook_deliveries import WebhookDelivery
from app.models.webhook_subscriptions import WebhookSubscription
from app.repositories.processed_webhook_events import ProcessedWebhookEventRepository

logger = logging.getLogger(__name__)


def _exponential_backoff(retries: int, base: int = 10, cap: int = 900) -> int:
    delay = min(base * (2 ** retries), cap)
    jitter = min(delay * 0.1, 10)
    return int(delay + (hash(str(retries)) % jitter))


@shared_task(bind=True, max_retries=7, default_retry_delay=10)
def deliver_webhook_task(self, subscription_id: str, event_type: str, data: dict, event_id: str | None = None) -> dict:
    async def _deliver() -> dict:
        from app.core.database import async_session_factory

        async with async_session_factory() as session:
            sub = await session.get(WebhookSubscription, uuid.UUID(subscription_id))
            if not sub or not sub.active:
                return {"status": "skipped", "reason": "subscription_inactive"}

            if not event_id:
                event_id = f"evt_{uuid.uuid4().hex[:12]}"

            processed_repo = ProcessedWebhookEventRepository(session)
            existing = await processed_repo.get_by_event_id(event_id)
            if existing:
                if existing.status == "processed":
                    return {"status": "deduplicated", "event_id": event_id}
                if existing.status == "processing":
                    return {"status": "in_progress", "event_id": event_id}
                if existing.status == "failed":
                    retry_after = existing.received_at.timestamp() + _exponential_backoff(existing.error.count(str(existing.error)) if existing.error else 0)
                    if datetime.now(timezone.utc).timestamp() < retry_after:
                        return {"status": "backoff", "event_id": event_id}

            processed_repo.create(
                event_id=event_id,
                source="internal",
                event_type=event_type,
                status="processing",
                payload={"subscription_id": subscription_id, "data": data},
                received_at=datetime.now(timezone.utc),
            )
            await session.commit()

            payload = {
                "id": event_id,
                "type": event_type,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "project_id": str(sub.project_id),
                "organization_id": getattr(sub, "organization_id", None),
                "data": data,
            }

            if sub.secret:
                signature = hmac.new(sub.secret.encode(), json.dumps(payload).encode(), hashlib.sha256).hexdigest()
                payload["signature"] = signature

            response_status = None
            response_body = None
            latency_ms = None
            attempts = self.request.retries + 1

            try:
                start = datetime.now(timezone.utc)
                async with httpx.AsyncClient(timeout=sub.timeout_seconds) as client:
                    response = await client.post(sub.url, json=payload)
                    latency_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
                    response_status = response.status_code
                    response_body = response.text[:4096] if response.text else None

                    delivery = WebhookDelivery(
                        subscription_id=sub.id,
                        event_type=event_type,
                        payload=payload,
                        response_status=response_status,
                        response_body=response_body,
                        latency_ms=latency_ms,
                        attempts=attempts,
                        delivered_at=datetime.now(timezone.utc),
                    )
                    session.add(delivery)

                    if response.status_code >= 400:
                        logger.warning("Webhook delivery failed: %s -> %s", sub.url, response.status_code)
                        await session.commit()
                        processed_repo = ProcessedWebhookEventRepository(session)
                        processed = await processed_repo.get_by_event_id(event_id)
                        if processed:
                            processed.status = "failed"
                            processed.error = f"HTTP {response.status_code}: {response_body[:200]}"
                            await session.commit()
                        raise Exception(f"Webhook failed with {response.status_code}")
            except Exception as exc:
                logger.error("Webhook delivery error: %s", exc)
                processed_repo = ProcessedWebhookEventRepository(session)
                processed = await processed_repo.get_by_event_id(event_id)
                if processed:
                    processed.status = "failed"
                    processed.error = str(exc)
                    await session.commit()
                self.retry(exc=exc, countdown=_exponential_backoff(self.request.retries))

            processed_repo = ProcessedWebhookEventRepository(session)
            processed = await processed_repo.get_by_event_id(event_id)
            if processed:
                processed.status = "processed"
                await session.commit()

            return {"status": "delivered", "event_id": event_id, "attempts": attempts}

    return run_async(_deliver())
