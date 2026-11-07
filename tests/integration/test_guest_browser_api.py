"""Actual browser -> same-origin API -> PostgreSQL; only PayPal is mocked."""

import asyncio
import json
import os
from pathlib import Path
import shutil
import select as io_select
import socket
import subprocess
import threading
import time
import uuid

from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import httpx
import pytest
from sqlalchemy import event, select
import uvicorn

from tipping_point.app import create_app
from tipping_point.db.models import Booking, GuestSession, PaymentOperation
from tipping_point.db.session import SessionLocal
from tipping_point.guest.payments import BookingPaymentService
from tipping_point.paypal.client import PayPalGateway
from tipping_point.settings import AppSettings
from tests.integration.api_helpers import logged_in_client, viable_workshop_body
from tests.integration.test_guest_payments import SandboxFixture

ROOT = Path(__file__).resolve().parents[2]


def test_browser_reservation_uses_real_api_cookies_and_durable_mock_payment(owned):
    chrome = os.environ.get("CHROME_PATH", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    if not Path(chrome).is_file() or not shutil.which("node"):
        pytest.skip("installed Chrome and Node are required; no browser package is downloaded")
    dist = ROOT / "frontend/dist"
    if not (dist / "index.html").is_file():
        pytest.skip("production frontend must be built before browser/API verification")
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    base = f"http://127.0.0.1:{listener.getsockname()[1]}"
    settings = AppSettings(
        _env_file=None, allow_insecure_dev_cookies=True,
        allowed_origins=base, public_url=base, paypal_expected_payee="PAYEE",
        paypal_client_id="offline-browser-client", paypal_client_secret="offline-browser-secret",
    )
    app = create_app(settings)
    host, info = logged_in_client(owned, app=app)
    body = viable_workshop_body(
        title="Browser integration — offline PayPal fixture",
        ticket_price_minor=2500, capacity=1, fixed_costs_minor=0,
    )
    body["financials"].update({
        "minimum_operating_attendance": 1, "materials": [], "contingency_minor": 0,
        "fee_estimate": {"percent_basis_points": 0, "fixed_minor": 0, "label": "explicit offline browser fixture"},
    })
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    body["schedule"] = {"opens_at": (now - timedelta(minutes=1)).isoformat(),
                        "closes_at": (now + timedelta(hours=2)).isoformat()}
    created = host.post("/api/merchant/workshops", json=body, headers={"X-CSRF-Token": info["csrf"]})
    assert created.status_code == 201, created.text
    wid = created.json()["workshop_id"]
    published = host.post(f"/api/merchant/workshops/{wid}/publish", headers={"X-CSRF-Token": info["csrf"]})
    assert published.status_code == 201, published.text
    provider = SandboxFixture("not-created-yet")

    def mocked_provider(request):
        if request.method == "POST" and request.url.path == "/v2/checkout/orders":
            provider.booking_id = json.loads(request.content)["purchase_units"][0]["reference_id"]
        return provider(request)

    gateway = PayPalGateway.from_settings(settings, transport=httpx.MockTransport(mocked_provider))
    app.state.paypal_gateway = gateway
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="test-assets")

    @app.get("/{frontend_path:path}")
    def frontend(frontend_path: str):
        if frontend_path.startswith("api/"):
            return JSONResponse({"detail": "not found"}, status_code=404)
        return FileResponse(dist / ("favicon.svg" if frontend_path == "favicon.svg" else "index.html"))

    # Exact mapper events register only rows this test creates, including when a
    # browser assertion fails before it can report a booking identifier.
    def register_guest(mapper, connection, target):
        owned.add(GuestSession, target.id)

    def register_booking(mapper, connection, target):
        owned.add(Booking, target.id)

    event.listen(GuestSession, "after_insert", register_guest)
    event.listen(Booking, "after_insert", register_booking)
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    child = None
    try:
        thread.start()
        deadline = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(.05)
        assert server.started, "isolated test API did not start"
        child = subprocess.Popen(
            [shutil.which("node"), str(ROOT / "frontend/tests/guest-api-browser.mjs"), base, wid],
            cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1,
        )
        phases = []
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            ready, _, _ = io_select.select([child.stdout], [], [], min(30, max(0, deadline - time.monotonic())))
            assert ready, "Browser/API harness did not report its next phase"
            line = child.stdout.readline()
            if not line:
                break
            result = json.loads(line)
            phases.append(result["phase"])
            print("Browser/API phase:", result["phase"], flush=True)
            booking_id = uuid.UUID(result["booking_id"])
            if result["phase"] == "APPROVE_FIXTURE":
                provider.approved = True  # Simulate buyer approval, never authorization.
                child.stdin.write("APPROVED\n"); child.stdin.flush()
            elif result["phase"] == "RELEASE_FIXTURE":
                with SessionLocal() as db:
                    booking = db.get(Booking, booking_id)
                    assert booking.state == "RELEASE_PENDING" and booking.admitted_at is not None
                    void = db.scalar(select(PaymentOperation).where(
                        PaymentOperation.booking_id == booking_id, PaymentOperation.kind == "VOID",
                    ))
                    request_id = void.request_id
                    released = asyncio.run(BookingPaymentService(db, settings, gateway).release_pending(booking_id))
                    assert released.state == "VOIDED"
                    assert db.get(PaymentOperation, void.id).request_id == request_id
                child.stdin.write("VOIDED\n"); child.stdin.flush()
            elif result["phase"] == "DONE":
                child.stdin.close()
                break
        code = child.wait(timeout=30)
        assert code == 0, child.stderr.read()
        assert phases == ["APPROVE_FIXTURE", "RELEASE_FIXTURE", "DONE"]
        assert provider.voided
        assert sum(path.endswith("/authorize") for _, path in provider.calls) == 1
        assert sum(path.endswith("/void") for _, path in provider.calls) == 1
    finally:
        if child and child.poll() is None:
            child.terminate(); child.wait(timeout=10)
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()
        event.remove(GuestSession, "after_insert", register_guest)
        event.remove(Booking, "after_insert", register_booking)
        asyncio.run(gateway.aclose())
        host.close()
