from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import uuid

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from tipping_point.app import create_app
from tipping_point.guest.schemas import EmptyRequest, ReservationRequest
from tipping_point.guest.service import availability, capacity_predicate, payload_hash
from tipping_point.settings import AppSettings


@pytest.mark.parametrize("origin", [
    "https://bookings.example.test", "http://localhost:8000", "http://127.0.0.1:8000", "http://[::1]:8000",
])
def test_public_origin_accepts_only_configured_safe_origins(origin):
    assert AppSettings(_env_file=None, public_url=origin).public_url == origin


@pytest.mark.parametrize("origin", [
    "http://bookings.example.test", "https://example.test/path", "https://user:password@example.test",
    "https://example.test?redirect=1", "https://example.test#fragment", "//example.test", "",
])
def test_public_origin_rejects_unsafe_or_nonbare_values(origin):
    with pytest.raises(ValidationError):
        AppSettings(_env_file=None, public_url=origin)


def test_settings_aliases_and_hosted_origin():
    settings = AppSettings(_env_file=None, TIPPING_POINT_PAYPAL_EXPECTED_PAYEE="merchant",
                           TIPPING_POINT_PUBLIC_URL="https://app.example.test")
    assert settings.paypal_expected_payee == "merchant"
    assert settings.public_url == "https://app.example.test"
    with pytest.raises(RuntimeError):
        AppSettings(_env_file=None, environment="hosted", cookie_secure=True,
                    public_url="http://localhost").validate_startup()


def test_guest_bootstrap_cookie_and_origin_rejection_are_offline():
    app = create_app(AppSettings(_env_file=None, allow_insecure_dev_cookies=True))
    with TestClient(app) as client:
        response = client.get("/api/guest/csrf")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert "tipping_guest_bootstrap=" in response.headers["set-cookie"]
        assert "SameSite=lax" in response.headers["set-cookie"] and "Path=/" in response.headers["set-cookie"]
        assert "Domain=" not in response.headers["set-cookie"]
        assert "tipping_csrf" not in client.cookies and "tipping_session" not in client.cookies
        # Rejected before DB lookup: these tests never connect to PostgreSQL.
        denied = client.post("/api/guest/session", json={}, headers={"Origin": "https://foreign.test"})
        assert denied.status_code == 403 and denied.json()["detail"]["code"] == "ORIGIN_NOT_ALLOWED"
        missing = client.post("/api/guest/session", json={})
        assert missing.status_code == 403 and missing.json()["detail"]["code"] == "CSRF_INVALID"


def test_reservation_input_is_small_and_never_accepts_financial_authority():
    key = uuid.uuid4()
    parsed = ReservationRequest(email=" Guest@Example.test ", idempotency_key=key)
    assert parsed.email == "guest@example.test"
    with pytest.raises(ValidationError):
        ReservationRequest(email="guest@example.test", idempotency_key=key, amount_minor=1)
    with pytest.raises(ValidationError):
        EmptyRequest(provider_order_id="browser-selected-order")
    assert payload_hash({"a": 1, "b": 2}) == payload_hash({"b": 2, "a": 1})


def test_availability_gates_configuration_window_schema_and_capacity():
    now = datetime.now(timezone.utc)
    campaign = SimpleNamespace(id=uuid.uuid4(), status="OPEN", cutoff_at=now + timedelta(hours=2), capacity=1)
    terms = SimpleNamespace(is_frozen=True, currency="GBP", opens_at=now - timedelta(minutes=1),
                            closes_at=campaign.cutoff_at)
    settings = SimpleNamespace(reservations_configured=False)
    db = SimpleNamespace(scalar=lambda _: 1)
    assert availability(db, campaign, terms, settings, now=now)[1] == "payment_unconfigured"
    settings.reservations_configured = True
    assert availability(db, campaign, terms, settings, now=now, schema_available=False)[1] == "schema_unavailable"
    assert availability(db, campaign, terms, settings, now=now, schema_available=True) == (False, "full", 0)
    db.scalar = lambda _: 0
    assert availability(db, campaign, terms, settings, now=now, schema_available=True) == (True, "available", 1)
    assert availability(db, campaign, terms, settings, now=campaign.cutoff_at)[1] == "closed"
    assert availability(db, campaign, terms, settings, now=terms.opens_at - timedelta(seconds=1))[1] == "not_open_yet"
    campaign.status = "DECIDING"
    assert availability(db, campaign, terms, settings, now=now)[1] == "ineligible"


def test_capacity_sql_retains_admitted_uncertain_resources():
    predicate = str(capacity_predicate(datetime.now(timezone.utc)).compile(dialect=postgresql.dialect()))
    assert "admitted_at IS NOT NULL" in predicate
    assert "reservation_expires_at >" in predicate
    assert "cancelled_at IS NULL" in predicate
