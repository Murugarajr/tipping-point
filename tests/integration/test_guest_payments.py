"""MockTransport provider responses with real PostgreSQL persistence."""

import asyncio
from datetime import datetime, timedelta, timezone
import json
import uuid

import httpx
import pytest
from sqlalchemy import select

from tipping_point.db.models import Booking, BookingEvent, PaymentOperation
from tipping_point.db.session import SessionLocal
from tipping_point.guest.payments import BookingPaymentService
from tipping_point.paypal.client import PayPalGateway
from .test_guest_reservations import guest_case


class SandboxFixture:
    def __init__(self, booking_id):
        self.booking_id = booking_id
        self.order_id = "OFFLINEORDER" + uuid.uuid4().hex[:10]
        self.auth_id = "OFFLINEAUTH" + uuid.uuid4().hex[:10]
        self.approved = False
        self.authorized = False
        self.voided = False
        self.unknown_create = False
        self.unknown_authorize = False
        self.payee = "PAYEE"
        self.auth_status = "CREATED"
        self.calls = []

    def order(self):
        unit = {"reference_id": self.booking_id, "payee": {"merchant_id": self.payee},
                "amount": {"currency_code": "GBP", "value": "25.00"}}
        if self.authorized:
            unit["payments"] = {"authorizations": [{
                "id": self.auth_id, "status": self.auth_status,
                "amount": {"currency_code": "GBP", "value": "25.00"},
            }]}
        return {
            "id": self.order_id, "intent": "AUTHORIZE",
            "status": "COMPLETED" if self.authorized else "APPROVED" if self.approved else "CREATED",
            "purchase_units": [unit], "links": [{
                "rel": "payer-action", "href": f"https://www.sandbox.paypal.com/checkoutnow?token={self.order_id}",
            }],
        }

    def __call__(self, request):
        path = request.url.path
        self.calls.append((request.method, path))
        if path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "offline-token", "expires_in": 3600})
        if request.method == "POST" and path == "/v2/checkout/orders":
            body = json.loads(request.content)
            assert body["payment_source"]["paypal"]["experience_context"]["return_url"].endswith(
                f"/bookings/{self.booking_id}/paypal/return"
            )
            if self.unknown_create:
                raise httpx.ReadTimeout("offline unknown", request=request)
            return httpx.Response(201, json=self.order())
        if path.endswith("/authorize"):
            self.authorized = True
            if self.unknown_authorize:
                raise httpx.ReadTimeout("offline unknown", request=request)
            return httpx.Response(201, json=self.order())
        if path.endswith("/void"):
            self.voided = True
            return httpx.Response(204)
        if path.startswith("/v2/checkout/orders/"):
            return httpx.Response(200, json=self.order())
        if path.startswith("/v2/payments/authorizations/"):
            now = datetime.now(timezone.utc)
            return httpx.Response(200, json={
                "id": self.auth_id, "status": "VOIDED" if self.voided else self.auth_status,
                "amount": {"currency_code": "GBP", "value": "25.00"},
                "supplementary_data": {"related_ids": {"order_id": self.order_id}},
                "create_time": now.isoformat(), "expiration_time": (now + timedelta(days=29)).isoformat(),
            })
        raise AssertionError("Unexpected offline provider request")


def setup_payment(case):
    result = case.reserve()
    assert result.status_code == 201
    booking_id = result.json()["booking_id"]
    provider = SandboxFixture(booking_id)
    gateway = PayPalGateway.from_settings(case.settings, transport=httpx.MockTransport(provider))
    case.app.state.paypal_gateway = gateway
    return booking_id, provider, gateway


def action(case, booking_id, suffix):
    return case.client.post(f"/api/bookings/{booking_id}/{suffix}", json={},
                            headers={"X-CSRF-Token": case.csrf})


def test_order_approval_authorization_and_exact_resource_release(guest_case):
    case = guest_case
    booking_id, provider, gateway = setup_payment(case)
    try:
        result = action(case, booking_id, "paypal/order")
        assert result.status_code == 200 and result.json()["payment_state"] == "AWAITING_APPROVAL"
        assert action(case, booking_id, "paypal/order").json()["booking_id"] == booking_id
        assert sum(path == "/v2/checkout/orders" for _, path in provider.calls) == 1
        assert action(case, booking_id, "paypal/authorize").status_code == 409
        provider.approved = True
        authorized = action(case, booking_id, "paypal/authorize")
        assert authorized.status_code == 200 and authorized.json()["state"] == "AUTHORIZED"
        assert "not a completed charge" in authorized.json()["notice"]
        assert action(case, booking_id, "paypal/authorize").json()["state"] == "AUTHORIZED"
        assert action(case, booking_id, "cancel").json()["state"] == "RELEASE_PENDING"
        with SessionLocal() as db:
            payments = BookingPaymentService(db, case.settings, gateway)
            released = asyncio.run(payments.release_pending(uuid.UUID(booking_id)))
            assert released.state == "VOIDED"
        assert provider.voided
        assert action(case, booking_id, "cancel").json()["state"] == "VOIDED"
        with SessionLocal() as db:
            assert asyncio.run(BookingPaymentService(db, case.settings, gateway).reconcile(
                uuid.UUID(booking_id)
            )).state == "VOIDED"
        assert sum(path.endswith("/authorize") for _, path in provider.calls) == 1
        assert sum(path.endswith(f"/{provider.auth_id}/void") for _, path in provider.calls) == 1
    finally:
        asyncio.run(gateway.aclose())


def test_unknown_create_never_replaced_and_known_reference_validated(guest_case):
    case = guest_case
    booking_id, provider, gateway = setup_payment(case)
    try:
        provider.unknown_create = True
        assert action(case, booking_id, "paypal/order").json()["state"] == "REVIEW_REQUIRED"
        assert action(case, booking_id, "paypal/order").json()["state"] == "REVIEW_REQUIRED"
        assert sum(path == "/v2/checkout/orders" for _, path in provider.calls) == 1
        provider.unknown_create = False
        with SessionLocal() as db:
            result = asyncio.run(BookingPaymentService(db, case.settings, gateway).reconcile(
                uuid.UUID(booking_id), provider.order_id
            ))
            assert result.state == "AWAITING_APPROVAL"
        assert sum(path == "/v2/checkout/orders" for _, path in provider.calls) == 1
    finally:
        asyncio.run(gateway.aclose())


@pytest.mark.parametrize("late", [False, True])
def test_unknown_authorization_resume_or_late_release(guest_case, late):
    case = guest_case
    booking_id, provider, gateway = setup_payment(case)
    try:
        action(case, booking_id, "paypal/order")
        provider.approved = True
        provider.unknown_authorize = True
        assert action(case, booking_id, "paypal/authorize").json()["state"] == "REVIEW_REQUIRED"
        if late:
            with SessionLocal() as db:
                db.get(Booking, uuid.UUID(booking_id)).reservation_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
                db.commit()
        resumed = action(case, booking_id, "paypal/authorize").json()
        assert resumed["state"] == ("RELEASE_PENDING" if late else "AUTHORIZED")
        with SessionLocal() as db:
            operations = list(db.scalars(select(PaymentOperation).where(
                PaymentOperation.booking_id == uuid.UUID(booking_id), PaymentOperation.kind == "AUTHORIZE"
            )))
            assert len(operations) == 1 and operations[0].state == "SUCCEEDED"
        assert sum(path.endswith("/authorize") for _, path in provider.calls) == 1
    finally:
        asyncio.run(gateway.aclose())


def test_mismatching_payee_preserves_order_evidence_without_authorizing(guest_case):
    case = guest_case
    booking_id, provider, gateway = setup_payment(case)
    try:
        provider.payee = "FOREIGN"
        response = action(case, booking_id, "paypal/order")
        assert response.status_code == 409
        with SessionLocal() as db:
            events = list(db.scalars(select(BookingEvent).where(BookingEvent.booking_id == uuid.UUID(booking_id))))
            assert any(event.details.get("order_id") == provider.order_id for event in events)
        assert not any(path.endswith("/authorize") for _, path in provider.calls)
    finally:
        asyncio.run(gateway.aclose())
