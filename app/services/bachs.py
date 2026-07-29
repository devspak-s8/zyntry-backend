from __future__ import annotations

import hashlib
import hmac
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx
from pydantic import BaseModel

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("app.services.bachs")


class BachsError(Exception):
    def __init__(self, message: str, status_code: int | None = None, body: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class BachsCheckoutSession(BaseModel):
    checkout_id: str
    checkout_url: str
    status: str
    expires_at: str | None = None
    created_at: str | None = None
    reference: str | None = None


class BachsCustomer(BaseModel):
    id: str | None = None
    email: str
    name: str


class BachsService:
    BASE_URL = "https://api.bachs.io/v1"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or settings.BACHS_API_KEY
        if not self.api_key:
            raise ValueError("Bachs API key is not configured")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _request(self, method: str, path: str, body: Any = None, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.BASE_URL}{path}"
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            response = await client.request(method, url, json=body, params=params, headers=self._headers())

        if response.status_code >= 200 and response.status_code < 300:
            return response.json()

        try:
            data = response.json()
        except Exception:
            data = {"detail": response.text}

        raise BachsError(
            message=data.get("detail") or data.get("message") or "Bachs request failed",
            status_code=response.status_code,
            body=data,
        )

    async def create_checkout_session(
        self,
        *,
        amount: str,
        currency: str = "USD",
        success_url: str | None = None,
        cancel_url: str | None = None,
        customer: BachsCustomer | None = None,
        metadata: dict[str, Any] | None = None,
        reference: str | None = None,
        expires_in_minutes: int = 60,
        allowed_payment_method_types: list[str] | None = None,
    ) -> BachsCheckoutSession:
        body: dict[str, Any] = {
            "pricing": {
                "currency": currency,
                "amount": amount,
                "price_type": "fixed",
            },
            "success_url": success_url or f"{settings.APP_URL}/billing?success=true",
            "cancel_url": cancel_url or f"{settings.APP_URL}/billing?canceled=true",
            "expires_in_minutes": expires_in_minutes,
            "metadata": metadata or {},
        }

        if customer:
            body["customer"] = customer.model_dump()

        if reference:
            body["reference"] = reference

        if allowed_payment_method_types:
            body["allowed_payment_method_types"] = allowed_payment_method_types

        data = await self._request("POST", "/checkout-sessions", body=body)
        return BachsCheckoutSession(
            checkout_id=data["checkout_id"],
            checkout_url=data["checkout_url"],
            status=data["status"],
            expires_at=data.get("expires_at"),
            created_at=data.get("created_at"),
            reference=data.get("reference"),
        )

    async def get_checkout_session(self, checkout_id: str) -> BachsCheckoutSession:
        data = await self._request("GET", f"/checkout-sessions/{checkout_id}")
        return BachsCheckoutSession(
            checkout_id=data["checkout_id"],
            checkout_url=data.get("checkout_url", ""),
            status=data["status"],
            expires_at=data.get("expires_at"),
            created_at=data.get("created_at"),
            reference=data.get("reference"),
        )

    async def create_customer(self, email: str, name: str, phone_number: str | None = None) -> BachsCustomer:
        body: dict[str, Any] = {"email": email, "name": name}
        if phone_number:
            body["phone_number"] = phone_number

        data = await self._request("POST", "/customers", body=body)
        return BachsCustomer(
            id=data.get("id", ""),
            email=data.get("email", email),
            name=data.get("name", name),
        )

    async def get_customer(self, customer_id: str) -> BachsCustomer:
        data = await self._request("GET", f"/customers/{customer_id}")
        return BachsCustomer(
            id=data.get("id", customer_id),
            email=data.get("email", ""),
            name=data.get("name", ""),
        )

    async def list_customers(self, search: str | None = None, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if search:
            params["search"] = search
        return await self._request("GET", "/customers", params=params)

    async def create_refund(self, checkout_id: str, amount: str | None = None, reason: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"checkout_id": checkout_id}
        if amount:
            body["amount"] = amount
        if reason:
            body["reason"] = reason
        return await self._request("POST", "/refunds", body=body)

    async def get_payment(self, charge_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/payments/{charge_id}")

    async def list_payments(self, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        return await self._request("GET", "/payments", params={"limit": limit, "offset": offset})

    async def get_balances(self) -> dict[str, Any]:
        return await self._request("GET", "/accounts/balances")


def verify_bachs_signature(raw_body: bytes, secret: str, timestamp_header: str, signature_header: str, tolerance_seconds: int = 300) -> bool:
    try:
        timestamp = int(timestamp_header)
    except (TypeError, ValueError):
        return False

    if abs(time.time() - timestamp) > tolerance_seconds:
        return False

    message = f"{timestamp}.{raw_body.decode('utf-8')}"
    expected = hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)
