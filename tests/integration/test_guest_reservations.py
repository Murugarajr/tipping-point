"""PostgreSQL-only test sources; children must not execute these DB mutations."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import uuid

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from tipping_point.app import create_app
from tipping_point.auth.service import hash_token
from tipping_point.db.models import Booking, Campaign, CampaignTerms, GuestSession, Merchant, Workshop
from tipping_point.db.session import SessionLocal
from tipping_point.economics import CampaignFinancialsInput, build_snapshot_hash
from tipping_point.settings import AppSettings


@pytest.fixture
def guest_case(owned):
    now = datetime.now(timezone.utc)
    merchant_id, workshop_id, terms_id, campaign_id = [uuid.uuid4() for _ in range(4)]
    inputs = CampaignFinancialsInput(
        currency="GBP", ticket_price_minor=2500, capacity=1,
        fee_estimate={"percent_basis_points": 0, "fixed_minor": 0, "label": "explicit offline test assumption"},
    )
    opens, closes = now - timedelta(minutes=1), now + timedelta(hours=4)
    with SessionLocal() as db:
        db.add(Merchant(id=merchant_id, name="Guest test " + uuid.uuid4().hex))
        db.flush()
        db.add(Workshop(id=workshop_id, merchant_id=merchant_id, title="Guest craft test",
                        capacity=1, ticket_price_minor=2500, currency="GBP"))
        db.flush()
        db.add(CampaignTerms(
            id=terms_id, workshop_id=workshop_id, version=1, currency="GBP",
            financial_inputs=inputs.model_dump(mode="json"), assumption_labels={},
            calculation={}, algorithm_version="test",
            snapshot_hash=build_snapshot_hash(inputs, opens_at=opens, closes_at=closes),
            opens_at=opens, closes_at=closes, is_frozen=True, frozen_at=now,
        ))
        db.flush()
        db.add(Campaign(id=campaign_id, workshop_id=workshop_id, terms_id=terms_id,
                        status="OPEN", capacity=1, cutoff_at=closes, terms_version=1))
        db.commit()
    owned.add(Merchant, merchant_id)
    settings = AppSettings(_env_file=None, allow_insecure_dev_cookies=True,
                           paypal_client_id="offline-test-client", paypal_client_secret="offline-test-secret",
                           paypal_expected_payee="PAYEE", public_url="http://localhost:8000")
    app = create_app(settings)
    clients = []

    def guest():
        client = TestClient(app)
        clients.append(client)
        token = client.get("/api/guest/csrf").json()["csrf_token"]
        response = client.post("/api/guest/session", json={}, headers={"X-CSRF-Token": token})
        assert response.status_code == 200
        with SessionLocal() as db:
            guest_id = db.scalar(select(GuestSession.id).where(
                GuestSession.token_hash == hash_token(client.cookies["tipping_guest_session"])
            ))
        owned.add(GuestSession, guest_id)
        return client, response.json()["csrf_token"], guest_id

    client, csrf, guest_id = guest()

    def reserve(*, client=client, csrf=csrf, key=None, email="guest@example.test"):
        return client.post(f"/api/campaigns/{campaign_id}/bookings",
                           json={"email": email, "idempotency_key": str(key or uuid.uuid4())},
                           headers={"X-CSRF-Token": csrf})

    yield SimpleNamespace(
        app=app, settings=settings, client=client, csrf=csrf, guest_id=guest_id,
        campaign_id=campaign_id, workshop_id=workshop_id, terms_id=terms_id,
        reserve=reserve, guest=guest,
    )
    for client in clients:
        client.close()


def test_guest_cookie_independence_restore_csrf_and_ownership(guest_case):
    case = guest_case
    cookies = case.client.cookies
    assert "tipping_guest_session" in cookies and "tipping_guest_csrf" in cookies
    assert "tipping_session" not in cookies and "tipping_csrf" not in cookies
    assert case.client.get("/api/guest/session").json()["csrf_token"] == case.csrf
    result = case.reserve()
    assert result.status_code == 201
    booking_id = result.json()["booking_id"]
    other, other_csrf, _ = case.guest()
    assert other.get(f"/api/bookings/{booking_id}").status_code == 404
    # Same contact email does not confer ownership.
    foreign = other.post(f"/api/bookings/{booking_id}/cancel", json={},
                         headers={"X-CSRF-Token": other_csrf})
    assert foreign.status_code == 404
    invalid = case.client.post(f"/api/bookings/{booking_id}/cancel", json={})
    assert invalid.status_code == 403 and invalid.json()["detail"]["code"] == "CSRF_INVALID"
    origin = case.client.post(f"/api/bookings/{booking_id}/cancel", json={},
                             headers={"X-CSRF-Token": case.csrf, "Origin": "https://untrusted.test"})
    assert origin.status_code == 403 and origin.json()["detail"]["code"] == "ORIGIN_NOT_ALLOWED"
    with SessionLocal() as db:
        db.get(GuestSession, case.guest_id).expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    assert case.client.get(f"/api/bookings/{booking_id}").status_code == 401


def test_reservation_idempotency_lost_key_and_backend_money(guest_case):
    case = guest_case
    key = uuid.uuid4()
    first = case.reserve(key=key)
    assert first.status_code == 201
    assert first.json()["amount_minor"] == 2500 and first.json()["currency"] == "GBP"
    assert first.json()["state"] == "CHECKOUT_RESERVED"
    assert case.reserve(key=key).json()["booking_id"] == first.json()["booking_id"]
    assert case.reserve().json()["booking_id"] == first.json()["booking_id"]
    conflict = case.reserve(key=key, email="changed@example.test")
    assert conflict.status_code == 409 and conflict.json()["detail"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert case.client.post(f"/api/campaigns/{case.campaign_id}/bookings",
        json={"email": "guest@example.test", "idempotency_key": str(uuid.uuid4()), "amount_minor": 1},
        headers={"X-CSRF-Token": case.csrf}).status_code == 422


def test_expired_hold_releases_capacity_without_browser_cleanup(guest_case):
    case = guest_case
    first = case.reserve().json()
    other, csrf, _ = case.guest()
    full = case.reserve(client=other, csrf=csrf)
    assert full.status_code == 409 and full.json()["detail"]["code"] == "CAPACITY_EXHAUSTED"
    with SessionLocal() as db:
        db.get(Booking, uuid.UUID(first["booking_id"])).reservation_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    assert case.reserve(client=other, csrf=csrf).status_code == 201
    assert case.client.get(f"/api/bookings/{first['booking_id']}").json()["state"] == "EXPIRED"


def test_admitted_release_uncertainty_keeps_capacity(guest_case):
    case = guest_case
    first = case.reserve().json()
    with SessionLocal() as db:
        row = db.get(Booking, uuid.UUID(first["booking_id"]))
        row.admitted_at = datetime.now(timezone.utc)
        row.state = "REVIEW_REQUIRED"
        row.reservation_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    other, csrf, _ = case.guest()
    assert case.reserve(client=other, csrf=csrf).status_code == 409
    assert case.client.get(f"/api/bookings/{first['booking_id']}").json()["seat_held"] is True
