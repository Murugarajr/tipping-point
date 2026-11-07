"""Hide from discovery / Restore visibility: listing metadata only (real PostgreSQL, no provider calls)."""

import asyncio
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from tipping_point.auth.passwords import hash_password
from tipping_point.db.engine import engine
from tipping_point.db.models import (
    Booking, BookingEvent, Campaign, CampaignDecision, CampaignTerms, DecisionCohortMember,
    MerchantCredential, PaymentOperation, SettlementWork, Workshop, WorkshopVisibilityEvent,
)
from tipping_point.db.session import SessionLocal
from tipping_point.settlement.dispatch import discover_due, process_due
from .api_helpers import logged_in_client, login_client
from .test_guest_reservations import guest_case  # noqa: F401
from .test_settlement import settlement_case  # noqa: F401

HIDE, RESTORE = "hide-from-discovery", "restore-visibility"


def host_for(owned, app, workshop_id):
    """Log in through the real auth flow as the merchant that owns ``workshop_id``."""
    with SessionLocal() as db:
        merchant_id = db.scalar(select(Workshop.merchant_id).where(Workshop.id == workshop_id))
        credential_id, login = uuid.uuid4(), f"visibility-{uuid.uuid4().hex[:12]}"
        db.add(MerchantCredential(id=credential_id, merchant_id=merchant_id, login_identifier=login,
                                  password_hash=hash_password("correct-horse-battery-test")))
        db.commit()
    owned.add(MerchantCredential, credential_id)
    client = TestClient(app)
    status, info = login_client(client, login, "correct-horse-battery-test")
    assert status == 200, info
    return client, info["csrf_token"]


def act(client, csrf, workshop_id, action, **headers):
    return client.post(f"/api/merchant/workshops/{workshop_id}/{action}",
                       headers={"X-CSRF-Token": csrf, **headers} if csrf is not None else headers)


def _rows(db, model, *conditions):
    return sorted(
        ({c.key: getattr(row, c.key) for c in model.__table__.columns} for row in db.scalars(select(model).where(*conditions))),
        key=lambda item: str(item["id"]),
    )


def financial_fingerprint(workshop_id):
    """Every terms/campaign/booking/payment/audit/settlement column tied to this workshop."""
    with SessionLocal() as db:
        campaign_ids = list(db.scalars(select(Campaign.id).where(Campaign.workshop_id == workshop_id)))
        booking_ids = list(db.scalars(select(Booking.id).where(Booking.campaign_id.in_(campaign_ids))))
        decision_ids = list(db.scalars(select(CampaignDecision.id).where(CampaignDecision.campaign_id.in_(campaign_ids))))
        return {
            "terms": _rows(db, CampaignTerms, CampaignTerms.workshop_id == workshop_id),
            "campaigns": _rows(db, Campaign, Campaign.workshop_id == workshop_id),
            "bookings": _rows(db, Booking, Booking.id.in_(booking_ids)),
            "operations": _rows(db, PaymentOperation, PaymentOperation.booking_id.in_(booking_ids)),
            "booking_events": _rows(db, BookingEvent, BookingEvent.booking_id.in_(booking_ids)),
            "decisions": _rows(db, CampaignDecision, CampaignDecision.id.in_(decision_ids)),
            "cohort": _rows(db, DecisionCohortMember, DecisionCohortMember.decision_id.in_(decision_ids)),
            "work": _rows(db, SettlementWork, SettlementWork.campaign_id.in_(campaign_ids)),
        }


def events(workshop_id):
    with SessionLocal() as db:
        return [(e.action, e.previous_hidden_at, e.hidden_from_discovery_at) for e in db.scalars(
            select(WorkshopVisibilityEvent).where(WorkshopVisibilityEvent.workshop_id == workshop_id)
            .order_by(WorkshopVisibilityEvent.occurred_at))]


def host_ids(client, visibility=None):
    response = client.get("/api/merchant/workshops", params={"visibility": visibility} if visibility else None)
    assert response.status_code == 200, response.text
    return {item["workshop_id"]: item for item in response.json()}


def test_hide_and_restore_change_only_discovery_listing(owned, guest_case):
    case, wid = guest_case, str(guest_case.workshop_id)
    reserved = case.reserve()
    assert reserved.status_code == 201, reserved.text
    booking_id = reserved.json()["booking_id"]
    public = TestClient(case.app)
    stranger, _stranger_csrf, _ = case.guest()
    before_detail = public.get(f"/api/workshops/{wid}").json()
    before_status = case.client.get(f"/api/bookings/{booking_id}")
    stranger_before = stranger.get(f"/api/bookings/{booking_id}").status_code
    assert before_status.status_code == 200 and stranger_before != 200
    assert wid in {w["workshop_id"] for w in public.get("/api/workshops").json()}
    host, csrf = host_for(owned, case.app, case.workshop_id)
    assert host_ids(host)[wid]["hidden_from_discovery_at"] is None
    fingerprint = financial_fingerprint(case.workshop_id)

    hidden = act(host, csrf, wid, HIDE)
    assert hidden.status_code == 200, hidden.text
    assert hidden.json()["changed"] is True and hidden.json()["hidden_from_discovery_at"]
    # Public discovery excludes it; the direct link keeps its real status and availability.
    assert wid not in {w["workshop_id"] for w in public.get("/api/workshops").json()}
    assert public.get(f"/api/workshops/{wid}").json() == before_detail
    # Guest owner access and normal authorization rules are unchanged.
    after_status = case.client.get(f"/api/bookings/{booking_id}")
    assert after_status.status_code == 200 and after_status.json() == before_status.json()
    assert stranger.get(f"/api/bookings/{booking_id}").status_code == stranger_before
    # Host filters: default listed view omits it; Hidden and All include it with its timestamp.
    assert wid not in host_ids(host) and wid in host_ids(host, "all")
    assert host_ids(host, "hidden")[wid]["hidden_from_discovery_at"] == hidden.json()["hidden_from_discovery_at"]
    detail = host.get(f"/api/merchant/workshops/{wid}").json()
    assert detail["hidden_from_discovery_at"] == hidden.json()["hidden_from_discovery_at"]
    assert detail["campaign"]["status"] == "OPEN"
    assert host.get("/api/merchant/workshops", params={"visibility": "bogus"}).status_code == 422
    # Idempotent: no second audit event.
    again = act(host, csrf, wid, HIDE)
    assert again.status_code == 200 and again.json()["changed"] is False
    assert [e[0] for e in events(case.workshop_id)] == ["HIDE"]
    assert financial_fingerprint(case.workshop_id) == fingerprint

    restored = act(host, csrf, wid, RESTORE)
    assert restored.status_code == 200 and restored.json() == {
        "workshop_id": wid, "hidden_from_discovery_at": None, "changed": True}
    assert wid in {w["workshop_id"] for w in public.get("/api/workshops").json()}
    assert wid in host_ids(host) and wid not in host_ids(host, "hidden")
    assert act(host, csrf, wid, RESTORE).json()["changed"] is False
    history = events(case.workshop_id)
    assert [e[0] for e in history] == ["HIDE", "RESTORE"]
    assert history[0][1] is None and history[0][2] is not None
    assert history[1][1] == history[0][2] and history[1][2] is None  # restore records what it undid
    assert financial_fingerprint(case.workshop_id) == fingerprint
    assert public.get(f"/api/workshops/{wid}").json() == before_detail


def test_hidden_campaign_still_settles_and_hiding_makes_no_provider_calls(owned, settlement_case):
    case = settlement_case(n=1, price=100)
    with SessionLocal() as db:
        discover_due(db, campaign_id=case.campaign_id)  # deadline work exists before hiding
    from tipping_point.app import create_app
    app = create_app(case.settings)
    host, csrf = host_for(owned, app, case.workshop_id)
    fingerprint = financial_fingerprint(case.workshop_id)
    assert fingerprint["work"] and fingerprint["work"][0]["state"] == "READY"

    assert act(host, csrf, case.workshop_id, HIDE).json()["changed"] is True
    assert case.provider.calls == []  # hiding never reaches PayPal
    assert financial_fingerprint(case.workshop_id) == fingerprint
    public = TestClient(app)
    assert str(case.workshop_id) not in {w["workshop_id"] for w in public.get("/api/workshops").json()}
    assert public.get(f"/api/workshops/{case.workshop_id}").status_code == 200
    assert str(case.workshop_id) in host_ids(host, "hidden")

    # Deadline settlement proceeds exactly as for a listed campaign.
    with engine.connect() as connection, SessionLocal(bind=connection) as db:
        case.provider.local.db = db
        result = asyncio.run(process_due(db, case.settings, case.gateway, campaign_id=case.campaign_id))
    assert result and result[-1]["state"] == "CONFIRMED"
    assert len([c for c in case.provider.calls if c[0] == "POST" and c[1].endswith("/capture")]) == 1
    with SessionLocal() as db:
        assert db.get(Workshop, case.workshop_id).hidden_from_discovery_at is not None


def test_other_merchants_cannot_hide_restore_or_see_workshops(owned, guest_case):
    wid = str(guest_case.workshop_id)
    owner, owner_csrf = host_for(owned, guest_case.app, guest_case.workshop_id)
    other, info = logged_in_client(owned, app=guest_case.app)
    for action in (HIDE, RESTORE):
        response = act(other, info["csrf"], wid, action)
        assert response.status_code == 404, response.text  # existence not leaked
    assert events(guest_case.workshop_id) == []
    for view in (None, "listed", "hidden", "all"):
        assert wid not in host_ids(other, view)
    assert act(owner, owner_csrf, wid, HIDE).status_code == 200
    assert act(other, info["csrf"], wid, RESTORE).status_code == 404
    assert wid in host_ids(owner, "hidden") and [e[0] for e in events(guest_case.workshop_id)] == ["HIDE"]


def test_csrf_and_authentication_are_required(owned, guest_case):
    wid = str(guest_case.workshop_id)
    host, csrf = host_for(owned, guest_case.app, guest_case.workshop_id)
    for action in (HIDE, RESTORE):
        assert act(host, None, wid, action).status_code == 403
        assert act(host, "not-the-session-token", wid, action).status_code == 403
        assert act(TestClient(guest_case.app), csrf, wid, action).status_code == 401
    with SessionLocal() as db:
        assert db.get(Workshop, guest_case.workshop_id).hidden_from_discovery_at is None
        assert db.scalar(select(func.count()).select_from(WorkshopVisibilityEvent).where(
            WorkshopVisibilityEvent.workshop_id == guest_case.workshop_id)) == 0


def test_hidden_draft_stays_out_of_discovery_after_publication(owned):
    from tipping_point.app import app
    from .api_helpers import viable_workshop_body
    from datetime import datetime, timedelta, timezone
    host, info = logged_in_client(owned, app=app)
    body = viable_workshop_body(title="Hidden before publish", ticket_price_minor=2500, capacity=1, fixed_costs_minor=0)
    body["financials"].update({"minimum_operating_attendance": 1, "materials": [], "contingency_minor": 0,
                               "fee_estimate": {"percent_basis_points": 0, "fixed_minor": 0, "label": "explicit test assumption"}})
    now = datetime.now(timezone.utc)
    body["schedule"] = {"opens_at": (now - timedelta(minutes=1)).isoformat(), "closes_at": (now + timedelta(hours=2)).isoformat()}
    created = host.post("/api/merchant/workshops", json=body, headers={"X-CSRF-Token": info["csrf"]})
    wid = created.json()["workshop_id"]
    assert act(host, info["csrf"], wid, HIDE).json()["changed"] is True
    published = host.post(f"/api/merchant/workshops/{wid}/publish", headers={"X-CSRF-Token": info["csrf"]})
    assert published.status_code == 201, published.text
    public = TestClient(app)
    assert wid not in {w["workshop_id"] for w in public.get("/api/workshops").json()}
    assert public.get(f"/api/workshops/{wid}").status_code == 200
