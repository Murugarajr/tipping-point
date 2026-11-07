"""Authenticated workshop draft, preview, and publish API tests.

All requests go through the REAL authenticated HTTP surface; no
authentication dependency is overridden. Ownership is verified across
every action, including cross-merchant denial and caller-supplied
merchant ID rejection.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from tipping_point.app import app
from tipping_point.db.models import Campaign, CampaignTerms
from tipping_point.db.session import SessionLocal

from tests.integration.api_helpers import (
    logged_in_client,
    viable_workshop_body,
)


def _create_workshop(client: TestClient, csrf: str, **overrides) -> dict:
    body = viable_workshop_body(**overrides)
    response = client.post(
        "/api/merchant/workshops",
        json=body,
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_unauthenticated_workshop_requests_rejected():
    anon = TestClient(app)
    assert anon.get("/api/merchant/workshops").status_code == 401
    assert (
        anon.post("/api/merchant/workshops", json=viable_workshop_body()).status_code
        == 401
    )


def test_create_list_get_and_edit_draft_workshop(owned):
    client, info = logged_in_client(owned)
    csrf = info["csrf"]

    created = _create_workshop(client, csrf, title="Initial Title")
    workshop_id = created["workshop_id"]
    assert created["title"] == "Initial Title"
    assert created["is_frozen"] is False
    assert created["terms_version"] == 1

    # List returns own workshops.
    listed = client.get("/api/merchant/workshops")
    assert listed.status_code == 200
    assert [w["workshop_id"] for w in listed.json()] == [workshop_id]

    # Retrieve returns the same draft.
    fetched = client.get(f"/api/merchant/workshops/{workshop_id}")
    assert fetched.status_code == 200
    assert fetched.json()["title"] == "Initial Title"

    # Edit draft terms and title.
    edit_body = viable_workshop_body(title="Updated Title", ticket_price_minor=5500)
    edited = client.patch(
        f"/api/merchant/workshops/{workshop_id}",
        json=edit_body,
        headers={"X-CSRF-Token": csrf},
    )
    assert edited.status_code == 200
    assert edited.json()["title"] == "Updated Title"
    assert edited.json()["ticket_price_minor"] == 5500
    assert edited.json()["is_frozen"] is False


def test_caller_supplied_merchant_id_rejected(owned):
    client, info = logged_in_client(owned)
    other_client, other_info = logged_in_client(owned)
    body = viable_workshop_body()
    body["merchant_id"] = str(other_info["merchant_id"])
    response = client.post(
        "/api/merchant/workshops",
        json=body,
        headers={"X-CSRF-Token": info["csrf"]},
    )
    assert response.status_code == 422


def test_cross_merchant_access_denied_for_all_actions(owned):
    owner_client, owner_info = logged_in_client(owned)
    intruder_client, intruder_info = logged_in_client(owned)
    intruder_csrf = intruder_info["csrf"]

    created = _create_workshop(owner_client, owner_info["csrf"])
    wid = created["workshop_id"]

    # Intruder does not see owner's workshop in list.
    assert intruder_client.get("/api/merchant/workshops").json() == []

    # Retrieve, edit, preview, and publish all return 404 for another merchant.
    assert intruder_client.get(f"/api/merchant/workshops/{wid}").status_code == 404
    assert (
        intruder_client.patch(
            f"/api/merchant/workshops/{wid}",
            json=viable_workshop_body(title="Hijacked"),
            headers={"X-CSRF-Token": intruder_csrf},
        ).status_code
        == 404
    )
    assert (
        intruder_client.post(
            f"/api/merchant/workshops/{wid}/preview",
            headers={"X-CSRF-Token": intruder_csrf},
        ).status_code
        == 404
    )
    assert (
        intruder_client.post(
            f"/api/merchant/workshops/{wid}/publish",
            headers={"X-CSRF-Token": intruder_csrf},
        ).status_code
        == 404
    )


def test_preview_does_not_freeze_or_create_campaign(owned):
    client, info = logged_in_client(owned)
    csrf = info["csrf"]
    wid = _create_workshop(client, csrf)["workshop_id"]

    preview = client.post(
        f"/api/merchant/workshops/{wid}/preview",
        headers={"X-CSRF-Token": csrf},
    )
    assert preview.status_code == 200
    data = preview.json()
    assert data["is_viable_at_capacity"] is True
    assert data["first_viable_attendance"] == 4
    assert [p["attendance"] for p in data["attendance_curve"]] == [4, 5, 6, 7, 8]
    assert "not Channel3 data" in data["materials_note"]

    # Terms remain unfrozen and no campaign was created.
    fetched = client.get(f"/api/merchant/workshops/{wid}").json()
    assert fetched["is_frozen"] is False


def test_publish_freezes_snapshot_and_repeat_is_idempotent(owned):
    client, info = logged_in_client(owned)
    csrf = info["csrf"]
    wid = _create_workshop(client, csrf)["workshop_id"]

    first = client.post(
        f"/api/merchant/workshops/{wid}/publish",
        headers={"X-CSRF-Token": csrf},
    )
    assert first.status_code == 201
    c1 = first.json()
    assert c1["status"] == "OPEN"
    assert c1["workshop_id"] == wid
    assert c1["terms_version"] == 1
    assert c1["terms_snapshot_hash"]

    # Repeat publish returns the SAME campaign without creating a second.
    second = client.post(
        f"/api/merchant/workshops/{wid}/publish",
        headers={"X-CSRF-Token": csrf},
    )
    assert second.status_code == 200
    assert second.json()["campaign_id"] == c1["campaign_id"]
    assert second.json()["terms_id"] == c1["terms_id"]

    with SessionLocal() as session:
        campaigns = session.scalars(
            select(Campaign).where(Campaign.workshop_id == wid)
        ).all()
        terms = session.get(CampaignTerms, c1["terms_id"])
        assert len(campaigns) == 1
        assert terms is not None and terms.is_frozen is True


def test_published_terms_cannot_be_mutated(owned):
    client, info = logged_in_client(owned)
    csrf = info["csrf"]
    wid = _create_workshop(client, csrf)["workshop_id"]
    published = client.post(
        f"/api/merchant/workshops/{wid}/publish",
        headers={"X-CSRF-Token": csrf},
    ).json()

    # Editing after publish is rejected with 409 and frozen snapshot stays intact.
    attempt = client.patch(
        f"/api/merchant/workshops/{wid}",
        json=viable_workshop_body(title="Mutated", ticket_price_minor=9999),
        headers={"X-CSRF-Token": csrf},
    )
    assert attempt.status_code == 409
    after = client.get(f"/api/merchant/workshops/{wid}").json()
    assert after["ticket_price_minor"] == 5000
    with SessionLocal() as session:
        terms = session.get(CampaignTerms, published["terms_id"])
        assert terms.snapshot_hash == published["terms_snapshot_hash"]


def test_infeasible_or_incomplete_draft_cannot_publish(owned):
    client, info = logged_in_client(owned)
    csrf = info["csrf"]

    # Costs cannot be covered at maximum capacity -> publish rejected (409).
    infeasible = _create_workshop(
        client, csrf, ticket_price_minor=1000, capacity=4, fixed_costs_minor=50000
    )["workshop_id"]
    res = client.post(
        f"/api/merchant/workshops/{infeasible}/publish",
        headers={"X-CSRF-Token": csrf},
    )
    assert res.status_code == 409

    # Zero ticket price -> draft allowed, publish rejected (409).
    zero_price = _create_workshop(
        client, csrf, ticket_price_minor=0, fixed_costs_minor=1000
    )["workshop_id"]
    res2 = client.post(
        f"/api/merchant/workshops/{zero_price}/publish",
        headers={"X-CSRF-Token": csrf},
    )
    assert res2.status_code == 409

    # No OPEN campaign was created for either rejected workshop.
    with SessionLocal() as session:
        rows = session.scalars(
            select(Campaign).where(
                Campaign.workshop_id.in_([infeasible, zero_price])
            )
        ).all()
        assert rows == []

def test_short_sandbox_window_dates_survive_save_reload_publish_and_campaign(owned):
    """Editor-style millisecond instants: save -> persisted draft -> detail -> publish -> campaign cutoff."""
    client, info = logged_in_client(owned)
    csrf = info["csrf"]
    clicked = datetime.now(timezone.utc).replace(microsecond=598000)
    opens, closes = clicked - timedelta(minutes=1), clicked + timedelta(minutes=15)
    # The frontend sends Date.toISOString() spellings (UTC, millisecond precision, "Z").
    spell = lambda value: value.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    body = viable_workshop_body(ticket_price_minor=100, capacity=1, fixed_costs_minor=0)
    body["financials"].update(minimum_operating_attendance=1, materials=[], contingency_minor=0,
                              fee_estimate={"percent_basis_points": 0, "fixed_minor": 50,
                                            "label": "application test assumption"})
    body["schedule"] = {"opens_at": spell(opens), "closes_at": spell(closes)}
    created = client.post("/api/merchant/workshops", json=body, headers={"X-CSRF-Token": csrf})
    assert created.status_code == 201, created.text
    wid = created.json()["workshop_id"]

    def instants(payload):
        return datetime.fromisoformat(payload["opens_at"]), datetime.fromisoformat(payload["closes_at"])

    assert instants(created.json()) == (opens, closes)
    # A resave of the reloaded values (draftFromDetail -> payloadForSave) is stable.
    body["schedule"] = {"opens_at": spell(opens), "closes_at": spell(closes)}
    resaved = client.patch(f"/api/merchant/workshops/{wid}", json=body, headers={"X-CSRF-Token": csrf})
    assert resaved.status_code == 200, resaved.text
    detail = client.get(f"/api/merchant/workshops/{wid}")
    assert detail.status_code == 200 and instants(detail.json()) == (opens, closes)
    preview = client.post(f"/api/merchant/workshops/{wid}/preview", headers={"X-CSRF-Token": csrf})
    assert preview.status_code == 200, preview.text
    published = client.post(f"/api/merchant/workshops/{wid}/publish", headers={"X-CSRF-Token": csrf})
    assert published.status_code == 201, published.text
    assert datetime.fromisoformat(published.json()["cutoff_at"]) == closes
    with SessionLocal() as session:
        campaign = session.get(Campaign, published.json()["campaign_id"])
        terms = session.get(CampaignTerms, campaign.terms_id)
        assert (terms.opens_at, terms.closes_at, campaign.cutoff_at) == (opens, closes, closes)
        assert campaign.cutoff_at - terms.opens_at == timedelta(minutes=16)
    frozen = client.get(f"/api/merchant/workshops/{wid}")
    assert frozen.json()["is_frozen"] and instants(frozen.json()) == (opens, closes)
