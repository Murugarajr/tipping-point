"""PayPal Sandbox adapter regression tests against labeled fixtures.

These tests are fully offline: every request is served by
``httpx.MockTransport`` handlers returning fixture data, so no live
PayPal system is ever contacted and no real credentials are used.
"""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

import httpx
import pytest

from tipping_point.paypal import (
    PAYPAL_MAX_REFERENCE_ID_LENGTH,
    PAYPAL_MAX_REQUEST_ID_LENGTH,
    PayPalAuthError,
    PayPalAuthorization,
    PayPalGateway,
    PayPalOrder,
    PayPalOutcomeUnknownError,
    PayPalRequestError,
    PayPalResponseError,
    PayPalTimeoutError,
    PayPalUnavailableError,
    PayPalUnconfiguredError,
    PayPalVoidResult,
    format_minor_to_amount,
    parse_amount_to_minor,
    parse_authorization,
    parse_order,
)

CLIENT_ID = "fixture-paypal-client-id"
CLIENT_SECRET = "fixture-paypal-client-secret-not-real"
ACCESS_TOKEN = "fixture-access-token"
ORDER_ID = "3TX12345AB678901V"
AUTHORIZATION_ID = "0AB98765CD123456V"
OPERATION_ID = "fixture-operation-id"
APPROVE_URL = f"https://www.sandbox.paypal.com/checkoutnow?token={ORDER_ID}"


def token_payload() -> dict[str, object]:
    """Labeled OAuth token fixture."""
    return {
        "scope": "openid https://uri.paypal.com/services/payments/authorization",
        "access_token": ACCESS_TOKEN,
        "token_type": "Bearer",
        "app_id": "APP-80W284485P519543T",
        "expires_in": 32400,
        "nonce": "fixture-nonce",
    }


def order_payload(status: str = "CREATED") -> dict[str, object]:
    """Labeled Orders v2 order fixture."""
    return {
        "id": ORDER_ID,
        "status": status,
        "intent": "AUTHORIZE",
        "purchase_units": [
            {
                "reference_id": "booking-fixture-001",
                "payee": {"merchant_id": "sandbox-merchant-fixture"},
                "amount": {"currency_code": "GBP", "value": "25.00"},
            }
        ],
        "links": [
            {"href": APPROVE_URL, "rel": "approve", "method": "GET"},
            {
                "href": (
                    "https://api-m.sandbox.paypal.com"
                    f"/v2/checkout/orders/{ORDER_ID}"
                ),
                "rel": "self",
                "method": "GET",
            },
        ],
    }


def authorization_payload(status: str = "CREATED") -> dict[str, object]:
    """Labeled Payments v2 authorization fixture."""
    return {
        "id": AUTHORIZATION_ID,
        "status": status,
        "supplementary_data": {"related_ids": {"order_id": ORDER_ID}},
        "amount": {"currency_code": "GBP", "value": "25.00"},
        "seller_protection": {"status": "ELIGIBLE"},
        "create_time": "2026-11-06T10:00:00Z",
        "update_time": "2026-11-06T10:00:05Z",
        "expiration_time": "2026-11-09T10:00:05Z",
        "links": [
            {
                "href": (
                    "https://api-m.sandbox.paypal.com"
                    f"/v2/payments/authorizations/{AUTHORIZATION_ID}"
                ),
                "rel": "self",
                "method": "GET",
            },
            {
                "href": (
                    "https://api-m.sandbox.paypal.com"
                    f"/v2/payments/authorizations/{AUTHORIZATION_ID}/void"
                ),
                "rel": "void",
                "method": "POST",
            },
        ],
    }


def authorized_order_payload() -> dict[str, object]:
    """Labeled order fixture after authorize returns an authorization."""
    payload = order_payload(status="COMPLETED")
    payload["payments"] = {"authorizations": [authorization_payload()]}
    return payload


class FakeSandbox:
    """Offline handler for the scoped sandbox endpoints."""

    def __init__(self) -> None:
        self.token_calls: list[httpx.Request] = []
        self.api_calls: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            self.token_calls.append(request)
            return httpx.Response(200, json=token_payload())
        self.api_calls.append(request)
        path = request.url.path
        if path == "/v2/checkout/orders" and request.method == "POST":
            return httpx.Response(201, json=order_payload())
        if path == f"/v2/checkout/orders/{ORDER_ID}" and request.method == "GET":
            return httpx.Response(200, json=order_payload(status="APPROVED"))
        if (
            path == f"/v2/checkout/orders/{ORDER_ID}/authorize"
            and request.method == "POST"
        ):
            return httpx.Response(201, json=authorized_order_payload())
        if (
            path == f"/v2/payments/authorizations/{AUTHORIZATION_ID}"
            and request.method == "GET"
        ):
            return httpx.Response(200, json=authorization_payload())
        if (
            path == f"/v2/payments/authorizations/{AUTHORIZATION_ID}/void"
            and request.method == "POST"
        ):
            return httpx.Response(204)
        raise AssertionError(f"unexpected request {request.method} {path}")


def run_scenario(
    fake: FakeSandbox,
    scenario: Callable[[PayPalGateway], Awaitable[object]],
) -> object:
    """Run one async gateway scenario against a fake sandbox."""

    async def run() -> object:
        async with PayPalGateway(
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            transport=httpx.MockTransport(fake.handler),
        ) as gateway:
            return await scenario(gateway)

    return asyncio.run(run())


def run_transport_scenario(
    transport: httpx.AsyncBaseTransport,
    scenario: Callable[[PayPalGateway], Awaitable[object]],
) -> object:
    """Run one async gateway scenario against a custom transport."""

    async def run() -> object:
        async with PayPalGateway(
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            transport=transport,
        ) as gateway:
            return await scenario(gateway)

    return asyncio.run(run())


def test_oauth_uses_basic_credentials_and_form_grant() -> None:
    fake = FakeSandbox()
    run_scenario(fake, lambda gateway: gateway.get_order(ORDER_ID))
    token_request = fake.token_calls[0]
    expected_basic = base64.b64encode(
        f"{CLIENT_ID}:{CLIENT_SECRET}".encode()
    ).decode()
    assert token_request.method == "POST"
    assert token_request.url.path == "/v1/oauth2/token"
    assert token_request.headers["authorization"] == f"Basic {expected_basic}"
    assert token_request.headers["content-type"] == (
        "application/x-www-form-urlencoded"
    )
    assert token_request.read() == b"grant_type=client_credentials"


def test_bearer_token_is_cached_and_sent_on_api_requests() -> None:
    fake = FakeSandbox()

    async def scenario(gateway: PayPalGateway) -> object:
        await gateway.get_order(ORDER_ID)
        await gateway.get_authorization(AUTHORIZATION_ID)
        return None

    run_scenario(fake, scenario)
    assert len(fake.token_calls) == 1
    assert fake.api_calls[0].headers["authorization"] == f"Bearer {ACCESS_TOKEN}"
    assert fake.api_calls[1].headers["authorization"] == f"Bearer {ACCESS_TOKEN}"


def test_create_authorization_order_sends_authorize_intent_and_request_id() -> None:
    fake = FakeSandbox()
    order = run_scenario(
        fake,
        lambda gateway: gateway.create_authorization_order(
            reference_id="booking-fixture-001",
            amount_minor=2500,
            currency="GBP",
            description="Beginner embroidery workshop place",
            operation_id=OPERATION_ID,
        ),
    )
    assert isinstance(order, PayPalOrder)
    request = fake.api_calls[0]
    assert request.method == "POST"
    assert request.url.path == "/v2/checkout/orders"
    assert request.headers["paypal-request-id"] == OPERATION_ID
    assert request.headers["prefer"] == "return=representation"
    assert json.loads(request.read()) == {
        "intent": "AUTHORIZE",
        "purchase_units": [
            {
                "reference_id": "booking-fixture-001",
                "amount": {"currency_code": "GBP", "value": "25.00"},
                "description": "Beginner embroidery workshop place",
            }
        ],
    }
    assert order.provider_order_id == ORDER_ID
    assert order.status == "CREATED"
    assert order.intent == "AUTHORIZE"
    assert order.reference_id == "booking-fixture-001"
    assert order.payee_identifier == "sandbox-merchant-fixture"
    assert order.amount_minor == 2500
    assert order.currency == "GBP"
    assert order.approve_url == APPROVE_URL
    assert order.authorizations == ()


def test_mutation_timeout_has_unknown_outcome_and_preserves_operation_id() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json=token_payload())
        requests.append(request)
        raise httpx.ReadTimeout("fixture transport timeout", request=request)

    with pytest.raises(PayPalOutcomeUnknownError) as exc:
        run_transport_scenario(
            httpx.MockTransport(handler),
            lambda gateway: gateway.create_authorization_order(
                reference_id="booking-fixture-001",
                amount_minor=2500,
                currency="GBP",
                description="Beginner embroidery workshop place",
                operation_id=OPERATION_ID,
            ),
        )

    assert exc.value.operation_id == OPERATION_ID
    assert exc.value.mutation == "create_authorization_order"
    assert "fixture transport timeout" not in str(exc.value)
    assert len(requests) == 1
    assert requests[0].headers["paypal-request-id"] == OPERATION_ID


def test_read_only_timeout_is_not_reported_as_unknown_mutation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json=token_payload())
        raise httpx.ReadTimeout("fixture transport timeout", request=request)

    with pytest.raises(PayPalTimeoutError) as exc:
        run_transport_scenario(
            httpx.MockTransport(handler), lambda gateway: gateway.get_order(ORDER_ID)
        )

    assert "fixture transport timeout" not in str(exc.value)


def test_operation_id_uses_bounded_application_policy() -> None:
    fake = FakeSandbox()
    with pytest.raises(ValueError, match="application request-id"):
        run_scenario(
            fake,
            lambda gateway: gateway.create_authorization_order(
                reference_id="booking-fixture-001",
                amount_minor=2500,
                currency="GBP",
                description="Beginner embroidery workshop place",
                operation_id="x" * (PAYPAL_MAX_REQUEST_ID_LENGTH + 1),
            ),
        )
    assert fake.token_calls == []
    assert fake.api_calls == []


def test_get_order_is_read_only_without_idempotency_header() -> None:
    fake = FakeSandbox()
    order = run_scenario(fake, lambda gateway: gateway.get_order(ORDER_ID))
    assert isinstance(order, PayPalOrder)
    request = fake.api_calls[0]
    assert request.method == "GET"
    assert request.url.path == f"/v2/checkout/orders/{ORDER_ID}"
    assert "paypal-request-id" not in request.headers
    assert order.status == "APPROVED"
    assert order.intent == "AUTHORIZE"


def test_authorize_order_returns_created_authorization() -> None:
    fake = FakeSandbox()
    order = run_scenario(
        fake,
        lambda gateway: gateway.authorize_order(ORDER_ID, operation_id=OPERATION_ID),
    )
    assert isinstance(order, PayPalOrder)
    request = fake.api_calls[0]
    assert request.method == "POST"
    assert request.url.path == f"/v2/checkout/orders/{ORDER_ID}/authorize"
    assert request.headers["paypal-request-id"] == OPERATION_ID
    assert request.read() == b"{}"
    assert order.status == "COMPLETED"
    assert len(order.authorizations) == 1
    summary = order.authorizations[0]
    assert summary.authorization_id == AUTHORIZATION_ID
    assert summary.status == "CREATED"
    assert summary.amount_minor == 2500
    assert summary.currency == "GBP"


def test_get_authorization_normalizes_provider_resource() -> None:
    fake = FakeSandbox()
    authorization = run_scenario(
        fake, lambda gateway: gateway.get_authorization(AUTHORIZATION_ID)
    )
    assert isinstance(authorization, PayPalAuthorization)
    request = fake.api_calls[0]
    assert request.method == "GET"
    assert request.url.path == f"/v2/payments/authorizations/{AUTHORIZATION_ID}"
    assert "paypal-request-id" not in request.headers
    assert authorization.authorization_id == AUTHORIZATION_ID
    assert authorization.status == "CREATED"
    assert authorization.order_id == ORDER_ID
    assert authorization.amount_minor == 2500
    assert authorization.currency == "GBP"
    assert authorization.expiration_time == datetime(
        2026, 11, 9, 10, 0, 5, tzinfo=timezone.utc
    )
    assert authorization.seller_protection_status == "ELIGIBLE"
    assert any(link.rel == "void" for link in authorization.links)


def test_void_authorization_uses_request_id_and_maps_204() -> None:
    fake = FakeSandbox()
    result = run_scenario(
        fake,
        lambda gateway: gateway.void_authorization(
            AUTHORIZATION_ID, operation_id=OPERATION_ID
        ),
    )
    assert isinstance(result, PayPalVoidResult)
    request = fake.api_calls[0]
    assert request.method == "POST"
    assert request.url.path == (
        f"/v2/payments/authorizations/{AUTHORIZATION_ID}/void"
    )
    assert request.headers["paypal-request-id"] == OPERATION_ID
    assert request.read() == b"{}"
    assert result.authorization_id == AUTHORIZATION_ID
    assert result.status == "VOIDED"


class Void200Sandbox(FakeSandbox):
    """Fake sandbox whose void endpoint returns 200 with a body."""

    def handler(self, request: httpx.Request) -> httpx.Response:
        if (
            request.url.path
            == f"/v2/payments/authorizations/{AUTHORIZATION_ID}/void"
        ):
            self.api_calls.append(request)
            return httpx.Response(200, json=authorization_payload(status="VOIDED"))
        return super().handler(request)


def test_void_authorization_accepts_200_with_representation() -> None:
    fake = Void200Sandbox()
    result = run_scenario(
        fake,
        lambda gateway: gateway.void_authorization(
            AUTHORIZATION_ID, operation_id=OPERATION_ID
        ),
    )
    assert isinstance(result, PayPalVoidResult)
    assert result.authorization_id == AUTHORIZATION_ID
    assert result.status == "VOIDED"