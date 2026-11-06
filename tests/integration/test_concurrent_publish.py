"""Coordinated multi-connection concurrent-publish and preservation tests.

Uses separate threads with independent database connections / HTTP
requests synchronized on a barrier so both publish attempts enter the
publishing transaction concurrently against PostgreSQL. The row lock on
the workshop + the partial unique index ``uq_campaigns_one_open_per_workshop``
must guarantee that at most one OPEN campaign is ever created and both
callers receive a clean, consistent outcome.

Also verifies that the explicit-registration cleanup preserves the
persistent verification sentinel AND any unrelated record present before
a test runs.
"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from sqlalchemy import select

from tipping_point.app import app
from tipping_point.db.models import Campaign, CampaignTerms, Merchant, Workshop
from tipping_point.db.session import SessionLocal
from tipping_point.economics import publish_campaign

from tests.integration.api_helpers import (
    logged_in_client,
    viable_workshop_body,
)

SENTINEL_NAME = "SENTINEL-2026-11-06-verification-preservation"


def test_concurrent_publish_across_separate_db_connections(owned):
    """Two independent DB connections race to publish the same workshop."""
    client, info = logged_in_client(owned)
    created = client.post(
        "/api/merchant/workshops",
        json=viable_workshop_body(),
        headers={"X-CSRF-Token": info["csrf"]},
    ).json()
    workshop_id = uuid.UUID(created["workshop_id"])
    merchant_id = info["merchant_id"]

    barrier = threading.Barrier(2, timeout=10)

    def worker() -> tuple[uuid.UUID, bool]:
        # Each worker opens its OWN independent SQLAlchemy Session
        # (and therefore its own checkout from the connection pool).
        with SessionLocal() as session:
            merchant = session.get(Merchant, merchant_id)
            assert merchant is not None
            barrier.wait()
            campaign, was_created = publish_campaign(
                session, merchant=merchant, workshop_id=workshop_id
            )
            session.commit()
            return campaign.id, was_created

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker) for _ in range(2)]
        results = [f.result(timeout=15) for f in futures]

    campaign_ids = {cid for cid, _ in results}
    created_flags = sorted(flag for _, flag in results)
    # Exactly one created the campaign; the second observed the locked
    # committed state and returned the same campaign idempotently.
    assert len(campaign_ids) == 1
    assert created_flags == [False, True]

    with SessionLocal() as session:
        campaigns = session.scalars(
            select(Campaign).where(Campaign.workshop_id == workshop_id)
        ).all()
        assert len(campaigns) == 1
        assert campaigns[0].status == "OPEN"


def test_concurrent_http_publish_requests(owned):
    """Two concurrent HTTP publish requests through the real API."""
    client, info = logged_in_client(owned)
    csrf = info["csrf"]
    session_cookie = client.cookies.get("tipping_session")
    created = client.post(
        "/api/merchant/workshops",
        json=viable_workshop_body(title="Concurrent HTTP"),
        headers={"X-CSRF-Token": csrf},
    ).json()
    wid = created["workshop_id"]

    barrier = threading.Barrier(2, timeout=10)

    def http_worker() -> tuple[int, str]:
        local = TestClient(app)
        local.cookies.set("tipping_session", session_cookie)
        barrier.wait()
        res = local.post(
            f"/api/merchant/workshops/{wid}/publish",
            headers={"X-CSRF-Token": csrf},
        )
        return res.status_code, res.json()["campaign_id"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = [f.result(timeout=15) for f in [pool.submit(http_worker) for _ in range(2)]]

    statuses = sorted(code for code, _ in outcomes)
    cids = {cid for _, cid in outcomes}
    assert statuses == [200, 201]
    assert len(cids) == 1


def test_sentinel_and_unrelated_records_preserved_by_cleanup(migrated_database):
    """Unregistered records (including the sentinel) are never touched."""
    from tests.integration.conftest import _OwnedRecords
    from tipping_point.db.session import session_scope

    unrelated_id = uuid.uuid4()
    owned_id = uuid.uuid4()
    with session_scope() as session:
        session.add(Merchant(id=unrelated_id, name="Unrelated Bystander"))
        session.add(Merchant(id=owned_id, name="Owned By Test"))

    try:
        # Simulate the exact per-test cleanup for owned_id only.
        registry = _OwnedRecords()
        registry.add(Merchant, owned_id)
        with session_scope() as session:
            session.query(Merchant).filter(
                Merchant.id.in_(registry.merchants)
            ).delete(synchronize_session=False)

        with SessionLocal() as session:
            sentinel = session.scalars(
                select(Merchant).where(Merchant.name == SENTINEL_NAME)
            ).first()
            bystander = session.get(Merchant, unrelated_id)
            deleted = session.get(Merchant, owned_id)
            assert sentinel is not None
            assert bystander is not None
            assert deleted is None
    finally:
        # Clean up our bystander by its exact primary key.
        with session_scope() as session:
            row = session.get(Merchant, unrelated_id)
            if row is not None:
                session.delete(row)