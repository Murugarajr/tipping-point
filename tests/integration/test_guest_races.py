"""Guest capacity races use independent PostgreSQL connections and a held lock.

No live provider is contacted; payment calls use explicit MockTransport fixtures.
"""

from concurrent.futures import ThreadPoolExecutor
import asyncio
from datetime import datetime, timedelta, timezone
import threading
import uuid

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import event, select

from tipping_point.app import create_app
from tipping_point.auth.service import hash_token
from tipping_point.db.engine import engine
from tipping_point.db.session import SessionLocal
from tipping_point.settings import AppSettings
from tests.integration.api_helpers import logged_in_client, viable_workshop_body


def _guest_app():
    return create_app(AppSettings(
        _env_file=None,
        cookie_secure=False,
        allow_insecure_dev_cookies=True,
        allowed_origins="http://localhost:5173",
        paypal_client_id="offline-fixture-client",
        paypal_client_secret="offline-fixture-secret",
        paypal_expected_payee="FIXTUREMERCHANT",
        public_url="http://localhost:5173",
    ))


def _guest(app, owned):
    from tipping_point.db.models import GuestSession

    client = TestClient(app, base_url="http://localhost:5173")
    bootstrap = client.get("/api/guest/csrf")
    assert bootstrap.status_code == 200, bootstrap.text
    created = client.post(
        "/api/guest/session", json={},
        headers={"X-CSRF-Token": bootstrap.json()["csrf_token"]},
    )
    assert created.status_code in (200, 201), created.text
    token = client.cookies.get("tipping_guest_session")
    assert token
    with SessionLocal() as session:
        row = session.scalars(select(GuestSession).where(
            GuestSession.token_hash == hash_token(token)
        )).one()
        owned.add(GuestSession, row.id)
    return client, created.json()["csrf_token"]


def _one_seat_campaign(app, owned):
    host, info = logged_in_client(owned, app=app)
    body = viable_workshop_body(capacity=1, fixed_costs_minor=0)
    body["financials"].update({
        "minimum_operating_attendance": 1,
        "materials": [], "contingency_minor": 0,
        "fee_estimate": {"percent_basis_points": 0, "fixed_minor": 0,
                         "label": "explicit offline race-test assumption"},
    })
    now = datetime.now(timezone.utc)
    body["schedule"] = {
        "opens_at": (now - timedelta(minutes=10)).isoformat(),
        "closes_at": (now + timedelta(hours=1)).isoformat(),
    }
    created = host.post("/api/merchant/workshops", json=body,
                        headers={"X-CSRF-Token": info["csrf"]})
    assert created.status_code == 201, created.text
    published = host.post(
        f"/api/merchant/workshops/{created.json()['workshop_id']}/publish",
        headers={"X-CSRF-Token": info["csrf"]},
    )
    assert published.status_code == 201, published.text
    return uuid.UUID(published.json()["campaign_id"])


def test_last_seat_is_not_oversold_with_two_coordinated_database_connections(owned):
    from tipping_point.db.models import Booking, Campaign

    app = _guest_app()
    campaign_id = _one_seat_campaign(app, owned)
    guests = [_guest(app, owned), _guest(app, owned)]
    reached_lock = threading.Event()
    seen_connections = set()
    guard = threading.Lock()

    def before_statement(connection, cursor, statement, parameters, context, many):
        normalized = statement.lower()
        if "campaigns" not in normalized or "for update" not in normalized:
            return
        with guard:
            seen_connections.add(id(connection.connection.driver_connection))
            if len(seen_connections) >= 2:
                reached_lock.set()

    def reserve(index):
        client, csrf = guests[index]
        return client.post(
            f"/api/campaigns/{campaign_id}/bookings",
            json={"email": f"race-{index}@example.invalid",
                  "idempotency_key": str(uuid.uuid4())},
            headers={"X-CSRF-Token": csrf},
        )

    # Hold the campaign lock first. Both worker sessions must demonstrably
    # reach their own FOR UPDATE before the holder releases the final seat.
    with SessionLocal() as holder:
        holder.execute(select(Campaign).where(
            Campaign.id == campaign_id
        ).with_for_update()).scalar_one()
        event.listen(engine, "before_cursor_execute", before_statement)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(reserve, index) for index in range(2)]
                synchronized = reached_lock.wait(timeout=15)
                holder.commit()
                responses = [future.result(timeout=30) for future in futures]
            assert synchronized, "Both independent sessions did not reach the campaign lock"
        finally:
            holder.rollback()
            event.remove(engine, "before_cursor_execute", before_statement)

    assert len(seen_connections) >= 2
    successful = [response for response in responses if response.status_code in (200, 201)]
    rejected = [response for response in responses if response.status_code == 409]
    assert len(successful) == 1 and len(rejected) == 1, [
        (response.status_code, response.text) for response in responses
    ]
    with SessionLocal() as session:
        bookings = session.scalars(select(Booking).where(
            Booking.campaign_id == campaign_id
        )).all()
        for booking in bookings:
            owned.add(Booking, booking.id)
        assert len(bookings) == 1


def test_concurrent_order_requests_share_one_committed_logical_operation(owned, monkeypatch):
    from tipping_point.auth.dependencies import get_db
    from tipping_point.db.models import Booking, PaymentOperation
    from tipping_point.paypal.client import PayPalGateway

    app = _guest_app()
    campaign_id = _one_seat_campaign(app, owned)
    guest, csrf = _guest(app, owned)
    reserved = guest.post(
        f"/api/campaigns/{campaign_id}/bookings",
        json={"email": "order-race@example.invalid", "idempotency_key": str(uuid.uuid4())},
        headers={"X-CSRF-Token": csrf},
    )
    assert reserved.status_code in (200, 201), reserved.text
    booking_id = uuid.UUID(reserved.json()["booking_id"])
    owned.add(Booking, booking_id)
    provider_entered = threading.Event()
    release_provider = threading.Event()
    guard = threading.Lock()
    calls = []
    tracked_sessions = set()
    transaction_observations = []
    gateway_init = PayPalGateway.__init__

    def tracking_db():
        session = SessionLocal()
        with guard:
            tracked_sessions.add(session)
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            with guard:
                tracked_sessions.discard(session)
            session.close()

    app.dependency_overrides[get_db] = tracking_db

    async def transport(request):
        # The first request is paused before starting the contender, so these
        # observations refer only to the operation currently entering provider I/O.
        with guard:
            transaction_observations.append(all(not session.in_transaction() for session in tracked_sessions))
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "offline-token", "expires_in": 3600})
        assert request.method == "POST" and request.url.path == "/v2/checkout/orders"
        import json
        payload = json.loads(request.content)
        with guard:
            calls.append(request.headers.get("PayPal-Request-Id"))
        with SessionLocal() as observer:
            # NOWAIT proves the committed operation is visible and no campaign/
            # booking lock is kept across the mocked provider mutation.
            observer.execute(select(Booking).where(
                Booking.id == booking_id
            ).with_for_update(nowait=True)).scalar_one()
            operations = observer.scalars(select(PaymentOperation).where(
                PaymentOperation.booking_id == booking_id
            )).all()
            assert len(operations) == 1
        provider_entered.set()
        assert await asyncio.to_thread(release_provider.wait, 20)
        return httpx.Response(201, json={
            "id": "ORDERFIXTURE1", "status": "CREATED", "intent": "AUTHORIZE",
            "purchase_units": [{**payload["purchase_units"][0],
                                "payee": {"merchant_id": "FIXTUREMERCHANT"}}],
            "links": [{"rel": "approve", "href": "https://www.sandbox.paypal.com/checkoutnow?token=ORDERFIXTURE1",
                       "method": "GET"}],
        })

    def offline_gateway(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(transport)
        gateway_init(self, *args, **kwargs)

    monkeypatch.setattr(PayPalGateway, "__init__", offline_gateway)
    cookie = guest.cookies.get("tipping_guest_session")
    csrf_cookie = guest.cookies.get("tipping_guest_csrf")

    def create_order():
        local = TestClient(app, base_url="http://localhost:5173")
        local.cookies.set("tipping_guest_session", cookie)
        if csrf_cookie:
            local.cookies.set("tipping_guest_csrf", csrf_cookie)
        return local.post(
            f"/api/bookings/{booking_id}/paypal/order", json={},
            headers={"X-CSRF-Token": csrf},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(create_order)
        try:
            assert provider_entered.wait(timeout=15), "First request did not reach the mocked provider"
            second = pool.submit(create_order)
            competing_response = second.result(timeout=15)
            assert competing_response.status_code in (200, 202, 409), competing_response.text
            if competing_response.status_code in (200, 202):
                assert competing_response.json()["payment_state"] == "CHECKING"
        finally:
            release_provider.set()
        original_response = first.result(timeout=30)
    assert original_response.status_code in (200, 201, 202), original_response.text
    assert len(calls) == 1 and calls[0], "Concurrent requests submitted more than one provider mutation"
    assert transaction_observations and all(transaction_observations)
    with SessionLocal() as session:
        operations = session.scalars(select(PaymentOperation).where(
            PaymentOperation.booking_id == booking_id
        )).all()
        for operation in operations:
            owned.add(PaymentOperation, operation.id)
        assert len(operations) == 1
