from __future__ import annotations

import hashlib
import hmac
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_mock import MockerFixture

from app.services.bachs import BachsService, BachsError, verify_bachs_signature


@pytest.fixture
def bachs_service() -> BachsService:
    return BachsService(api_key="sk_test_bachs")


def _mock_response(status_code: int, json_data: dict[str, Any]) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.text = str(json_data)
    return resp


def test_verify_bachs_signature_valid(bachs_service: BachsService) -> None:
    secret = "whsec_test"
    timestamp = str(int(time.time()))
    body = b'{"id":"evt_test"}'
    message = f"{timestamp}.{body.decode('utf-8')}"
    signature = hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()

    assert verify_bachs_signature(body, secret, timestamp, signature) is True


def test_verify_bachs_signature_invalid(bachs_service: BachsService) -> None:
    body = b'{"id":"evt_test"}'
    assert verify_bachs_signature(body, "secret", "1234567890", "invalid_signature") is False


def test_verify_bachs_signature_stale(bachs_service: BachsService) -> None:
    body = b'{"id":"evt_test"}'
    old_timestamp = str(int(time.time()) - 400)
    message = f"{old_timestamp}.{body.decode('utf-8')}"
    signature = hmac.new(b"secret", message.encode("utf-8"), hashlib.sha256).hexdigest()

    assert verify_bachs_signature(body, "secret", old_timestamp, signature) is False


@pytest.mark.asyncio
async def test_create_checkout_session(mocker: MockerFixture, bachs_service: BachsService) -> None:
    mock_response = {
        "checkout_id": "chk_test123",
        "checkout_url": "https://checkout.bachs.io/c/chk_test123",
        "status": "OPEN",
        "expires_at": "2026-07-29T06:00:00.000Z",
        "created_at": "2026-07-28T06:00:00.000Z",
        "reference": "ref_test",
    }

    mock_client = AsyncMock()
    mock_response_obj = _mock_response(201, mock_response)
    mock_client.request.return_value = mock_response_obj
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    mocker.patch("httpx.AsyncClient", return_value=mock_client)

    checkout = await bachs_service.create_checkout_session(
        amount="20.00",
        currency="USD",
        success_url="https://example.com/success",
        cancel_url="https://example.com/cancel",
        reference="ref_test",
    )

    assert checkout.checkout_id == "chk_test123"
    assert checkout.checkout_url == "https://checkout.bachs.io/c/chk_test123"
    assert checkout.status == "OPEN"


@pytest.mark.asyncio
async def test_create_checkout_session_api_error(mocker: MockerFixture, bachs_service: BachsService) -> None:
    mock_client = AsyncMock()
    mock_response_obj = _mock_response(401, {"detail": "Invalid API key", "error_code": "UNAUTHORIZED"})
    mock_client.request.return_value = mock_response_obj
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    mocker.patch("httpx.AsyncClient", return_value=mock_client)

    with pytest.raises(BachsError) as exc_info:
        await bachs_service.create_checkout_session(amount="20.00", currency="USD")

    assert exc_info.value.status_code == 401
    assert "Invalid API key" in str(exc_info.value)


@pytest.mark.asyncio
async def test_get_checkout_session(mocker: MockerFixture, bachs_service: BachsService) -> None:
    mock_response = {
        "checkout_id": "chk_test123",
        "checkout_url": "https://checkout.bachs.io/c/chk_test123",
        "status": "COMPLETED",
    }

    mock_client = AsyncMock()
    mock_response_obj = _mock_response(200, mock_response)
    mock_client.request.return_value = mock_response_obj
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    mocker.patch("httpx.AsyncClient", return_value=mock_client)

    checkout = await bachs_service.get_checkout_session("chk_test123")
    assert checkout.status == "COMPLETED"


@pytest.mark.asyncio
async def test_create_customer(mocker: MockerFixture, bachs_service: BachsService) -> None:
    mock_response = {
        "id": "cust_test123",
        "email": "test@example.com",
        "name": "Test User",
    }

    mock_client = AsyncMock()
    mock_response_obj = _mock_response(201, mock_response)
    mock_client.request.return_value = mock_response_obj
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    mocker.patch("httpx.AsyncClient", return_value=mock_client)

    customer = await bachs_service.create_customer(email="test@example.com", name="Test User")
    assert customer.id == "cust_test123"
    assert customer.email == "test@example.com"


@pytest.mark.asyncio
async def test_list_customers(mocker: MockerFixture, bachs_service: BachsService) -> None:
    mock_response = {
        "items": [
            {"id": "cust_1", "email": "a@example.com", "name": "Alice"},
        ],
        "pagination": {"limit": 20, "offset": 0, "total": 1},
    }

    mock_client = AsyncMock()
    mock_response_obj = _mock_response(200, mock_response)
    mock_client.request.return_value = mock_response_obj
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    mocker.patch("httpx.AsyncClient", return_value=mock_client)

    result = await bachs_service.list_customers(search="a@example.com", limit=1)
    assert result["items"][0]["id"] == "cust_1"


@pytest.mark.asyncio
async def test_create_refund(mocker: MockerFixture, bachs_service: BachsService) -> None:
    mock_response = {
        "id": "ref_test123",
        "checkout_id": "chk_test123",
        "amount": "20.00",
        "currency": "USD",
        "status": "succeeded",
    }

    mock_client = AsyncMock()
    mock_response_obj = _mock_response(201, mock_response)
    mock_client.request.return_value = mock_response_obj
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    mocker.patch("httpx.AsyncClient", return_value=mock_client)

    refund = await bachs_service.create_refund(checkout_id="chk_test123", amount="20.00", reason="test refund")
    assert refund["id"] == "ref_test123"


@pytest.mark.asyncio
async def test_get_balances(mocker: MockerFixture, bachs_service: BachsService) -> None:
    mock_response = {
        "balances": [
            {"currency": "USD", "available": "1000.00", "locked": "0.00", "pending": "0.00"},
        ],
        "total_usd": "1000.00",
    }

    mock_client = AsyncMock()
    mock_response_obj = _mock_response(200, mock_response)
    mock_client.request.return_value = mock_response_obj
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    mocker.patch("httpx.AsyncClient", return_value=mock_client)

    balances = await bachs_service.get_balances()
    assert balances["total_usd"] == "1000.00"
