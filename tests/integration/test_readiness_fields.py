"""Additive read-only fields on the owned-workshop response: campaign.published_at and
campaign.settlement.decided_at. Real PostgreSQL (tipping_point_test); no provider calls."""

from datetime import datetime
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from tipping_point.app import create_app
from tipping_point.auth.passwords import hash_password
from tipping_point.db.models import Campaign, CampaignDecision, MerchantCredential, Workshop
from tipping_point.db.session import SessionLocal
from .api_helpers import logged_in_client, login_client
from .test_settlement import advance, settlement_case  # noqa: F401

# Response shape before this change; only the two new fields may be added.
PREVIOUS_CAMPAIGN_FIELDS = {"campaign_id", "workshop_id", "status", "capacity", "cutoff_at", "terms_version",
                            "terms_id", "terms_snapshot_hash", "settlement"}
PREVIOUS_SETTLEMENT_FIELDS = {
    "state", "decision_result", "decision_reason", "frozen_attendance", "admitted_attendance", "authorized_minor",
    "collected_minor", "refunded_minor", "net_collected_minor", "capture_pending", "release_pending", "refund_pending",
    "review_required", "settlement_deadline", "fee_basis", "actual_fees_minor", "estimated_fees_minor",
    "estimated_surplus_minor", "post_collection_surplus_minor", "sandbox_cleanup"}
PREVIOUS_TOP_LEVEL_FIELDS = {"workshop_id", "title", "description", "capacity", "ticket_price_minor", "currency",
                             "terms_version", "is_frozen", "opens_at", "closes_at", "campaign_id",
                             "hidden_from_discovery_at", "financials", "terms_snapshot_hash", "campaign",
                             "offer_stale_after_seconds"}


def owner_client(case):
    app = create_app(case.settings)
    client = TestClient(app)
    with SessionLocal() as db:
        workshop = db.get(Workshop, case.workshop_id)
        login = "readiness-" + uuid.uuid4().hex
        db.add(MerchantCredential(merchant_id=workshop.merchant_id, login_identifier=login,
                                  password_hash=hash_password("offline-password")))
        db.commit()
    assert login_client(client, login, "offline-password")[0] == 200
    return app, client


def parse(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_owned_workshop_returns_publication_and_decision_times(settlement_case):
    case = settlement_case(n=1)
    assert advance(case) == "CONFIRMED"
    _, client = owner_client(case)
    response = client.get(f"/api/merchant/workshops/{case.workshop_id}")
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    campaign = response.json()["campaign"]
    with SessionLocal() as db:
        created = db.get(Campaign, case.campaign_id).created_at
        frozen = db.scalar(select(CampaignDecision.frozen_at).where(CampaignDecision.campaign_id == case.campaign_id))
    assert parse(campaign["published_at"]) == created
    assert parse(campaign["settlement"]["decided_at"]) == frozen


def test_undecided_campaign_reports_null_decision_time(settlement_case):
    case = settlement_case(n=1)  # published and past cutoff, but no deadline decision frozen yet
    _, client = owner_client(case)
    campaign = client.get(f"/api/merchant/workshops/{case.workshop_id}").json()["campaign"]
    assert campaign["published_at"] is not None
    assert campaign["settlement"]["decided_at"] is None and campaign["settlement"]["decision_result"] is None


def test_cross_merchant_request_remains_refused(settlement_case, owned):
    case = settlement_case(n=1)
    assert advance(case) == "CONFIRMED"
    app, _ = owner_client(case)
    other, _ = logged_in_client(owned, app=app)
    refused = other.get(f"/api/merchant/workshops/{case.workshop_id}")
    assert refused.status_code == 404
    assert "published_at" not in refused.text and "decided_at" not in refused.text
    assert TestClient(app).get(f"/api/merchant/workshops/{case.workshop_id}").status_code == 401


def test_response_shape_is_unchanged_apart_from_the_two_fields(settlement_case):
    case = settlement_case(n=1)
    assert advance(case) == "CONFIRMED"
    _, client = owner_client(case)
    body = client.get(f"/api/merchant/workshops/{case.workshop_id}").json()
    assert set(body) == PREVIOUS_TOP_LEVEL_FIELDS
    assert set(body["campaign"]) == PREVIOUS_CAMPAIGN_FIELDS | {"published_at"}
    assert set(body["campaign"]["settlement"]) == PREVIOUS_SETTLEMENT_FIELDS | {"decided_at"}
    # Existing values are untouched by the addition.
    assert body["campaign"]["status"] == "CONFIRMED" and body["campaign"]["settlement"]["collected_minor"] == 1000
    # Read-only: the fields cannot be written through the existing edit endpoint.
    patch = client.patch(f"/api/merchant/workshops/{case.workshop_id}", json={"published_at": "2000-01-01T00:00:00Z"})
    assert patch.status_code in (403, 409, 422)
    assert client.get(f"/api/merchant/workshops/{case.workshop_id}").json()["campaign"]["published_at"] == body["campaign"]["published_at"]
