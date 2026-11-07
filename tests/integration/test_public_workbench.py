"""Real PostgreSQL/auth sessions; Channel3 is an explicit offline test fixture."""

import uuid

from fastapi.testclient import TestClient
from tipping_point.app import app
from tipping_point.db.models import CampaignTerms, Workshop
from tipping_point.db.session import SessionLocal
from tests.integration.api_helpers import logged_in_client, viable_workshop_body
from tests.integration.test_material_api import _fixture_client

PUBLIC_KEYS = {
    "workshop_id", "campaign_id", "title", "description", "currency",
    "ticket_price_minor", "capacity", "opens_at", "cutoff_at",
    "publication_status", "booking_window_status", "reservations_available",
    "availability_note", "availability_reason", "available_seats",
}


def create(client, csrf, body=None):
    response = client.post("/api/merchant/workshops", json=body or viable_workshop_body(), headers={"X-CSRF-Token": csrf})
    assert response.status_code == 201, response.text
    return response.json()["workshop_id"]


def save_body(detail):
    financials = {**detail["financials"], "materials": []}
    for item in detail["financials"]["materials"]:
        line = dict(item)
        provenance = line.pop("offer_provenance", None)
        if provenance:
            line["selected_offer_snapshot_id"] = provenance["offer_snapshot_id"]
        financials["materials"].append(line)
    return {
        "title": detail["title"], "description": detail["description"],
        "financials": financials,
        "schedule": {"opens_at": detail["opens_at"], "closes_at": detail["closes_at"]},
    }


def test_draft_reopens_edits_and_only_publication_enters_discovery(owned):
    client, info = logged_in_client(owned)
    other, other_info = logged_in_client(owned)
    anon = TestClient(app)
    wid = create(client, info["csrf"])
    url = f"/api/merchant/workshops/{wid}"
    detail = client.get(url)
    assert detail.headers["cache-control"] == "no-store"
    saved = detail.json()
    assert saved["financials"]["materials"][0]["name"] == "Clay"
    assert saved["financials"]["fee_estimate"]["percent_basis_points"] == 249
    assert saved["campaign"] is None
    assert anon.get(url).status_code == 401
    assert other.get(url).status_code == 404
    assert anon.get(f"/api/workshops/{wid}").status_code == 404
    assert wid not in {item["workshop_id"] for item in anon.get("/api/workshops").json()}
    body = save_body(saved)
    body["title"] = "A real test-owned workshop"
    body["financials"]["ticket_price_minor"] = 5205
    assert client.patch(url, json=body).status_code == 403
    assert client.patch(url, json=body, headers={"X-CSRF-Token": info["csrf"], "Origin": "https://attacker.invalid"}).status_code == 403
    assert other.patch(url, json=body, headers={"X-CSRF-Token": other_info["csrf"]}).status_code == 404
    edited = client.patch(url, json=body, headers={"X-CSRF-Token": info["csrf"]})
    assert edited.status_code == 200, edited.text
    reopened = client.get(url).json()
    assert reopened["financials"]["ticket_price_minor"] == 5205
    assert reopened["title"] == body["title"]
    preview = client.post(url + "/preview", headers={"X-CSRF-Token": info["csrf"]})
    assert preview.status_code == 200
    assert preview.json()["is_viable_at_capacity"]
    published = client.post(url + "/publish", headers={"X-CSRF-Token": info["csrf"]})
    assert published.status_code == 201, published.text
    campaign = published.json()
    assert client.get(url).json()["campaign"] == campaign
    repeated = client.post(url + "/publish", headers={"X-CSRF-Token": info["csrf"]})
    assert repeated.status_code == 200 and repeated.json() == campaign
    assert client.patch(url, json=body, headers={"X-CSRF-Token": info["csrf"]}).status_code == 409
    public_response = anon.get(f"/api/workshops/{wid}")
    assert public_response.status_code == 200
    public = public_response.json()
    assert set(public) == PUBLIC_KEYS
    assert public["campaign_id"] == campaign["campaign_id"]
    assert public["ticket_price_minor"] == 5205
    assert public["reservations_available"] is False
    assert public["booking_window_status"] == "not_open_yet"
    assert public["publication_status"] == "OPEN"
    assert public_response.headers["cache-control"] == "no-store"
    assert any(item["workshop_id"] == wid for item in anon.get("/api/workshops").json())

    # A test-owned mutable workshop summary cannot override frozen financial data.
    with SessionLocal() as db:
        row = db.get(Workshop, uuid.UUID(wid))
        row.ticket_price_minor = 999999
        row.capacity = 99
        db.commit()
    projected = anon.get(f"/api/workshops/{wid}").json()
    assert projected["ticket_price_minor"] == 5205 and projected["capacity"] == 8


def test_selected_offer_roundtrip_retains_facts_and_rejects_forgery(owned, monkeypatch):
    client, info = logged_in_client(owned)
    wid = create(client, info["csrf"])
    url = f"/api/merchant/workshops/{wid}"
    monkeypatch.setattr(app.state, "channel3_client", _fixture_client(), raising=False)
    search = client.post(url + "/materials/search", json={"query": "fixture needles"}, headers={"X-CSRF-Token": info["csrf"]})
    offer = search.json()["offers"][0]
    selection = {
        "offer_snapshot_id": offer["offer_snapshot_id"], "material_name": "Needles",
        "pack_size": 12, "shared_units": 0, "per_attendee_units": 2,
        "suitability_reviewed": True, "pack_size_reviewed": True,
        "shipping_allowance_minor": 450, "shipping_allowance_source": "reviewed fixture shipping",
    }
    selected = client.post(url + "/materials/select", json=selection, headers={"X-CSRF-Token": info["csrf"]})
    assert selected.status_code == 200, selected.text
    detail = client.get(url).json()
    provider_line = detail["financials"]["materials"][-1]
    assert provider_line["offer_provenance"]["retrieved_at"] == offer["retrieved_at"]
    body = save_body(detail)
    body["title"] = "Renamed without losing reviewed sourcing"
    saved = client.patch(url, json=body, headers={"X-CSRF-Token": info["csrf"]})
    assert saved.status_code == 200, saved.text
    after = client.get(url).json()
    assert after["financials"]["materials"][-1] == provider_line
    for field, value, status in [
        ("pack_price_minor", 1, 409),
        ("pack_size", 999, 409),
        ("selected_offer_snapshot_id", str(uuid.uuid4()), 422),
        ("offer_provenance", provider_line["offer_provenance"], 422),
    ]:
        forged = save_body(after)
        forged["financials"]["materials"][-1][field] = value
        response = client.patch(url, json=forged, headers={"X-CSRF-Token": info["csrf"]})
        assert response.status_code == status, response.text
    downgraded = save_body(after)
    downgraded["financials"]["materials"][-1].pop("selected_offer_snapshot_id")
    assert client.patch(url, json=downgraded, headers={"X-CSRF-Token": info["csrf"]}).status_code == 422
    assert client.get(url).json()["financials"]["materials"][-1] == provider_line
    public = TestClient(app).get(f"/api/workshops/{wid}")
    assert public.status_code == 404
    published = client.post(url + "/publish", headers={"X-CSRF-Token": info["csrf"]})
    assert published.status_code == 201, published.text
    exposed = TestClient(app).get(f"/api/workshops/{wid}").json()
    assert set(exposed) == PUBLIC_KEYS
    for private_field in ["financials", "materials", "offer_provenance", "merchant_id", "fee_estimate", "session_id"]:
        assert private_field not in exposed


def test_pack_jumps_remain_non_monotonic_and_preview_is_not_confirmation(owned):
    client, info = logged_in_client(owned)
    body = viable_workshop_body(ticket_price_minor=200, capacity=4, fixed_costs_minor=0)
    body["financials"].update({
        "minimum_operating_attendance": 1, "contingency_minor": 0,
        "fee_estimate": {"percent_basis_points": 0, "fixed_minor": 0, "label": "explicit zero-fee test assumption"},
        "materials": [{"name": "Packs", "source_label": "test assumption", "shared_units": 0,
                       "per_attendee_units": 1, "pack_size": 2, "pack_price_minor": 350}],
    })
    wid = create(client, info["csrf"], body)
    preview = client.post(f"/api/merchant/workshops/{wid}/preview", headers={"X-CSRF-Token": info["csrf"]}).json()
    assert preview["first_viable_attendance"] == 2
    assert [row["is_viable"] for row in preview["attendance_curve"]] == [False, True, False, True]
    assert TestClient(app).get(f"/api/workshops/{wid}").status_code == 404
    assert client.get(f"/api/merchant/workshops/{wid}").json()["campaign"] is None


def test_invalid_terms_never_enter_public_discovery(owned):
    client, info = logged_in_client(owned)
    for body in [viable_workshop_body(ticket_price_minor=0), viable_workshop_body(ticket_price_minor=100, fixed_costs_minor=50000)]:
        wid = create(client, info["csrf"], body)
        response = client.post(f"/api/merchant/workshops/{wid}/publish", headers={"X-CSRF-Token": info["csrf"]})
        assert response.status_code == 409
        assert TestClient(app).get(f"/api/workshops/{wid}").status_code == 404


def test_published_projection_does_not_read_newer_private_terms(owned):
    client, info = logged_in_client(owned)
    wid = create(client, info["csrf"])
    campaign = client.post(f"/api/merchant/workshops/{wid}/publish", headers={"X-CSRF-Token": info["csrf"]}).json()
    with SessionLocal() as db:
        frozen = db.get(CampaignTerms, uuid.UUID(campaign["terms_id"]))
        db.add(CampaignTerms(
            workshop_id=uuid.UUID(wid), version=2, currency="GBP",
            financial_inputs={**frozen.financial_inputs, "ticket_price_minor": 999999},
            assumption_labels={"private": "not public"}, calculation=frozen.calculation,
            algorithm_version=frozen.algorithm_version, snapshot_hash="f" * 64,
            opens_at=frozen.opens_at, closes_at=frozen.closes_at, is_frozen=False,
        ))
        db.commit()
    public = TestClient(app).get(f"/api/workshops/{wid}").json()
    assert public["ticket_price_minor"] == 5000
    assert public["campaign_id"] == campaign["campaign_id"]

def test_preview_and_reviewed_publication_bind_current_saved_hash(owned):
    client, info = logged_in_client(owned)
    other, other_info = logged_in_client(owned)
    wid = create(client, info["csrf"])
    url = f"/api/merchant/workshops/{wid}"
    saved = client.get(url).json()
    preview = client.post(url + "/preview", headers={"X-CSRF-Token": info["csrf"]}).json()
    assert preview["terms_version"] == saved["terms_version"]
    assert preview["terms_snapshot_hash"] == saved["terms_snapshot_hash"]
    reviewed = {
        "expected_terms_version": preview["terms_version"],
        "expected_terms_snapshot_hash": preview["terms_snapshot_hash"],
    }
    assert client.post(url + "/publish", json=reviewed).status_code == 403
    assert other.post(url + "/publish", json=reviewed, headers={"X-CSRF-Token": other_info["csrf"]}).status_code == 404
    edited = save_body(saved)
    edited["financials"]["ticket_price_minor"] += 100
    assert client.patch(url, json=edited, headers={"X-CSRF-Token": info["csrf"]}).status_code == 200
    current = client.get(url).json()
    assert current["terms_version"] == saved["terms_version"]
    assert current["terms_snapshot_hash"] != saved["terms_snapshot_hash"]
    stale = client.post(url + "/publish", json=reviewed, headers={"X-CSRF-Token": info["csrf"]})
    assert stale.status_code == 409
    assert "changed after review" in stale.json()["detail"]
    assert client.get(url).json()["is_frozen"] is False
    assert TestClient(app).get(f"/api/workshops/{wid}").status_code == 404
    fresh = client.post(url + "/preview", headers={"X-CSRF-Token": info["csrf"]}).json()
    reviewed = {
        "expected_terms_version": fresh["terms_version"],
        "expected_terms_snapshot_hash": fresh["terms_snapshot_hash"],
    }
    first = client.post(url + "/publish", json=reviewed, headers={"X-CSRF-Token": info["csrf"]})
    assert first.status_code == 201, first.text
    repeated = client.post(url + "/publish", json=reviewed, headers={"X-CSRF-Token": info["csrf"]})
    assert repeated.status_code == 200
    assert repeated.json() == first.json()
