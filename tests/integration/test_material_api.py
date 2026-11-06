"""Authenticated material workflow tests use labeled provider fixtures only."""

from __future__ import annotations

import uuid

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import select
from tipping_point.app import app
from tipping_point.channel3 import Channel3Client
from tipping_point.db.models import CampaignTerms, MaterialOfferSnapshot
from tipping_point.db.session import SessionLocal
from tipping_point.settings import AppSettings
from tests.integration.api_helpers import logged_in_client, viable_workshop_body


MOCK_CHANNEL3_RESPONSE = {
    "products": [{
        "id": "fixture-needle-product",
        "title": "Fixture needle kit",
        "brands": [{"id": "fixture-brand", "name": "Fixture Tools"}],
        "images": [{"url": "https://fixture.invalid/needles.png", "is_main_image": True}],
        "offers": [{
            "url": "https://fixture.invalid/needle-kit",
            "domain": "fixture.invalid",
            "price": {"price": 5.99, "currency": "GBP"},
            "availability": "InStock",
            "condition": "new",
        }],
    }],
    "next_page_token": None,
}


def _workshop(client, csrf: str) -> str:
    response = client.post(
        "/api/merchant/workshops",
        json=viable_workshop_body(),
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 201, response.text
    return response.json()["workshop_id"]


def _fixture_client() -> Channel3Client:
    return Channel3Client(
        api_key="fixture-not-a-real-channel3-key",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=MOCK_CHANNEL3_RESPONSE)
        ),
    )


def test_search_requires_session_csrf_and_origin_protection(owned, monkeypatch):
    anonymous = TestClient(app)
    no_session = anonymous.post(
        f"/api/merchant/workshops/{uuid.uuid4()}/materials/search",
        json={"query": "embroidery needles"},
    )
    assert no_session.status_code == 401
    client, info = logged_in_client(owned)
    workshop_id = _workshop(client, info["csrf"])
    monkeypatch.setattr(app.state, "channel3_client", _fixture_client(), raising=False)
    url = f"/api/merchant/workshops/{workshop_id}/materials/search"
    body = {"query": "embroidery needles"}
    assert client.post(url, json=body).status_code == 403
    assert client.post(url, json=body, headers={"X-CSRF-Token": "forged"}).status_code == 403
    evil = client.post(
        url,
        json=body,
        headers={"X-CSRF-Token": info["csrf"], "Origin": "https://attacker.invalid"},
    )
    assert evil.status_code == 403


def test_authenticated_search_persists_fixture_provenance_and_locale(owned, monkeypatch):
    client, info = logged_in_client(owned)
    workshop_id = _workshop(client, info["csrf"])
    monkeypatch.setattr(app.state, "channel3_client", _fixture_client(), raising=False)
    response = client.post(
        f"/api/merchant/workshops/{workshop_id}/materials/search",
        json={"query": "embroidery needles", "limit": 3},
        headers={"X-CSRF-Token": info["csrf"]},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert (data["locale_country"], data["locale_language"], data["locale_currency"]) == ("GB", "en", "GBP")
    assert len(data["offers"]) == 1
    offer = data["offers"][0]
    assert offer["product_title"] == "Fixture needle kit"
    assert offer["merchant_domain"] == "fixture.invalid"
    assert offer["price_minor"] == 599 and offer["currency"] == "GBP"
    assert offer["availability"] == "InStock"
    assert offer["provider_product_id"] == "fixture-needle-product"
    assert offer["retrieved_at"]
    with SessionLocal() as session:
        row = session.get(MaterialOfferSnapshot, offer["offer_snapshot_id"])
        assert row is not None
        assert row.workshop_id == uuid.UUID(workshop_id)
        assert row.merchant_id == info["merchant_id"]
        assert row.price_minor == 599




def test_offer_selection_requires_pack_and_shipping_review_and_updates_economics(owned, monkeypatch):
    client, info = logged_in_client(owned)
    workshop_id = _workshop(client, info["csrf"])
    monkeypatch.setattr(app.state, "channel3_client", _fixture_client(), raising=False)
    base = f"/api/merchant/workshops/{workshop_id}/materials"
    searched = client.post(
        f"{base}/search",
        json={"query": "embroidery needles"},
        headers={"X-CSRF-Token": info["csrf"]},
    )
    assert searched.status_code == 200, searched.text
    offer = searched.json()["offers"][0]
    before = client.post(
        f"/api/merchant/workshops/{workshop_id}/preview",
        headers={"X-CSRF-Token": info["csrf"]},
    ).json()
    selection = {
        "offer_snapshot_id": offer["offer_snapshot_id"],
        "material_name": "Fixture Needles",
        "kind": "consumable",
        "pack_size": 12,
        "shared_units": 0,
        "per_attendee_units": 2,
        "suitability_reviewed": True,
        "pack_size_reviewed": True,
        "review_notes": "Merchant fixture review: 12 needles per pack, two per attendee.",
        "shipping_allowance_minor": 450,
        "shipping_allowance_source": "Merchant estimate from supplier checkout; not verified.",
    }
    selected = client.post(
        f"{base}/select",
        json=selection,
        headers={"X-CSRF-Token": info["csrf"]},
    )
    assert selected.status_code == 200, selected.text
    data = selected.json()
    assert data["pack_price_minor"] == 599
    assert data["shipping_allowance_minor"] == 450
    assert data["shipping_allowance_source"].startswith("Merchant estimate")
    after = data["viability_preview"]
    assert after["attendance_curve"][-1]["material_cost_minor"] > 0
    assert after["attendance_curve"][-1]["required_budget_minor"] == (
        12000 + after["attendance_curve"][-1]["material_cost_minor"] + 450 + 500
    )
    assert after["attendance_curve"][-1]["required_budget_minor"] > before["attendance_curve"][-1]["required_budget_minor"]
    assert "no stock" in after["materials_note"]

    forged = {**selection, "price_minor": 1, "currency": "GBP"}
    assert client.post(
        f"{base}/select", json=forged, headers={"X-CSRF-Token": info["csrf"]}
    ).status_code == 422

    with SessionLocal() as session:
        terms = session.scalars(
            select(CampaignTerms).where(CampaignTerms.workshop_id == uuid.UUID(workshop_id))
        ).one()
        material = terms.financial_inputs["materials"][-1]
        assert material["pack_price_minor"] == 599
        assert material["offer_provenance"]["offer_snapshot_id"] == offer["offer_snapshot_id"]
        assert material["offer_provenance"]["retrieved_at"]
        assert terms.assumption_labels["shipping_allowance"] == selection["shipping_allowance_source"]


def test_cross_merchant_cannot_select_private_offer_or_search_owned_workshop(owned, monkeypatch):
    owner, owner_info = logged_in_client(owned)
    other, other_info = logged_in_client(owned)
    workshop_id = _workshop(owner, owner_info["csrf"])
    monkeypatch.setattr(app.state, "channel3_client", _fixture_client(), raising=False)
    searched = owner.post(
        f"/api/merchant/workshops/{workshop_id}/materials/search",
        json={"query": "embroidery needles"},
        headers={"X-CSRF-Token": owner_info["csrf"]},
    )
    offer_id = searched.json()["offers"][0]["offer_snapshot_id"]
    selection = {
        "offer_snapshot_id": offer_id,
        "material_name": "Private",
        "kind": "consumable",
        "pack_size": 12,
        "shared_units": 0,
        "per_attendee_units": 2,
        "suitability_reviewed": True,
        "pack_size_reviewed": True,
        "shipping_allowance_minor": 0,
        "shipping_allowance_source": "Merchant explicitly estimates no additional shipping.",
    }
    url = f"/api/merchant/workshops/{workshop_id}/materials/select"
    assert other.post(url, json=selection, headers={"X-CSRF-Token": other_info["csrf"]}).status_code == 404
    assert other.post(
        f"/api/merchant/workshops/{workshop_id}/materials/search",
        json={"query": "needle"},
        headers={"X-CSRF-Token": other_info["csrf"]},
    ).status_code == 404


def test_published_terms_cannot_be_searched_or_changed_and_snapshot_is_frozen(owned, monkeypatch):
    client, info = logged_in_client(owned)
    workshop_id = _workshop(client, info["csrf"])
    monkeypatch.setattr(app.state, "channel3_client", _fixture_client(), raising=False)
    materials = f"/api/merchant/workshops/{workshop_id}/materials"
    search = client.post(
        f"{materials}/search",
        json={"query": "embroidery needles"},
        headers={"X-CSRF-Token": info["csrf"]},
    )
    offer = search.json()["offers"][0]
    selection = client.post(
        f"{materials}/select",
        json={
            "offer_snapshot_id": offer["offer_snapshot_id"],
            "material_name": "Needles",
            "kind": "consumable",
            "pack_size": 12,
            "shared_units": 0,
            "per_attendee_units": 2,
            "suitability_reviewed": True,
            "pack_size_reviewed": True,
            "shipping_allowance_minor": 0,
            "shipping_allowance_source": "Merchant reviewed shipping as zero for this scenario.",
        },
        headers={"X-CSRF-Token": info["csrf"]},
    )
    assert selection.status_code == 200, selection.text
    publish = client.post(
        f"/api/merchant/workshops/{workshop_id}/publish",
        headers={"X-CSRF-Token": info["csrf"]},
    )
    assert publish.status_code == 201, publish.text
    frozen_before = client.get(f"/api/merchant/workshops/{workshop_id}").json()
    blocked = client.post(
        f"{materials}/search",
        json={"query": "new offer"},
        headers={"X-CSRF-Token": info["csrf"]},
    )
    assert blocked.status_code == 409
    edit = client.patch(
        f"/api/merchant/workshops/{workshop_id}",
        json=viable_workshop_body(title="Frozen change"),
        headers={"X-CSRF-Token": info["csrf"]},
    )
    assert edit.status_code == 409
    assert client.get(f"/api/merchant/workshops/{workshop_id}").json() == frozen_before
    with SessionLocal() as session:
        terms = session.scalars(
            select(CampaignTerms).where(CampaignTerms.workshop_id == uuid.UUID(workshop_id))
        ).one()
        provenance = terms.financial_inputs["materials"][-1]["offer_provenance"]
        assert provenance["offer_snapshot_id"] == offer["offer_snapshot_id"]
        assert provenance["retrieved_at"] == offer["retrieved_at"]
        snapshot = session.get(MaterialOfferSnapshot, offer["offer_snapshot_id"])
        assert snapshot is not None and snapshot.price_minor == 599
        assert snapshot.retrieved_at.isoformat() == offer["retrieved_at"].replace("Z", "+00:00")




def test_unconfigured_provider_and_missing_pack_review_are_explicit(owned):
    client, info = logged_in_client(owned)
    workshop_id = _workshop(client, info["csrf"])
    had_client = hasattr(app.state, "channel3_client")
    previous_client = getattr(app.state, "channel3_client", None)
    settings = app.state.settings
    app.state.settings = AppSettings(_env_file=None)
    try:
        app.state.channel3_client = Channel3Client(api_key=None)
        unconfigured = client.post(
            f"/api/merchant/workshops/{workshop_id}/materials/search",
            json={"query": "needle"},
            headers={"X-CSRF-Token": info["csrf"]},
        )
        assert unconfigured.status_code == 503
        assert unconfigured.json()["detail"]["state"] == "unconfigured"

        app.state.channel3_client = _fixture_client()
        searched = client.post(
            f"/api/merchant/workshops/{workshop_id}/materials/search",
            json={"query": "needle"},
            headers={"X-CSRF-Token": info["csrf"]},
        )
        offer_id = searched.json()["offers"][0]["offer_snapshot_id"]
        missing_review = client.post(
            f"/api/merchant/workshops/{workshop_id}/materials/select",
            json={
                "offer_snapshot_id": offer_id,
                "material_name": "Needles",
                "kind": "consumable",
                "pack_size": 1,
                "shared_units": 0,
                "per_attendee_units": 1,
                "suitability_reviewed": True,
                "pack_size_reviewed": False,
                "shipping_allowance_minor": 0,
                "shipping_allowance_source": "Merchant supplied no-shipping assumption.",
            },
            headers={"X-CSRF-Token": info["csrf"]},
        )
        assert missing_review.status_code == 422
    finally:
        app.state.settings = settings
        if had_client:
            app.state.channel3_client = previous_client
        else:
            del app.state.channel3_client
