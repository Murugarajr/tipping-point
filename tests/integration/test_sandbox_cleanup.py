"""Approved Sandbox operator-test cleanup: real PostgreSQL, MockTransport-only provider."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import pathlib
import runpy
import threading
from types import SimpleNamespace
import uuid

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError
from sqlalchemy import func, select, text

from tipping_point.app import create_app
from tipping_point.auth.passwords import hash_password
from tipping_point.auth.service import hash_token
from tipping_point.db.engine import engine
from tipping_point.db.models import (
    Booking, BookingEvent, Campaign, CampaignDecision, DecisionCohortMember, GuestSession, Merchant,
    MerchantCredential, PaymentOperation, SettlementWork, Workshop,
)
from tipping_point.db.session import SessionLocal
from tipping_point.guest.payments import BookingPaymentService
from tipping_point.guest.service import utcnow
from tipping_point.settings import AppSettings
from tipping_point.settlement.decision import CLEANUP_INTENT_KEY, CLEANUP_PURPOSE, enqueue
from tipping_point.settlement.dispatch import claim_due, discover_due, finish_work, process_due
from tipping_point.settlement.operator_cleanup import (
    ACTION, CleanupRejected, CleanupRequest, inspect_cleanup, request_cleanup, run_cleanup,
)
from tipping_point.settlement.service import SettlementService
from .api_helpers import login_client
from .test_settlement import SimulatedWorkerDeath, advance, settlement_case, state  # noqa: F401

REASON = "Sandbox GBP 1.00 operator test campaign cleanup"


def confirmed(settlement_case, n=1, price=100):
    """Confirm through the durable dispatcher, so the single work row finishes DONE as in practice."""
    case = settlement_case(n=n, price=price)
    with engine.connect() as connection, SessionLocal(bind=connection) as db:
        case.provider.local.db = db
        result = asyncio.run(process_due(db, case.settings, case.gateway, campaign_id=case.campaign_id))
    assert result and result[-1]["state"] == "CONFIRMED"
    return case


def req(case, **changes):
    b = case.rows[0]
    values = dict(campaign_id=case.campaign_id, booking_id=b.id, capture_id=b.capture_id,
                  expected_amount_minor=100, expected_currency="GBP", reason=REASON, action=ACTION)
    values.update(changes)
    return CleanupRequest(**values)


def request(case, request_=None, settings=None):
    with SessionLocal() as db:
        return request_cleanup(db, settings or case.settings, request_ or req(case))


def cleanup(case, request_=None, **kwargs):
    with engine.connect() as connection, SessionLocal(bind=connection) as db:
        case.provider.local.db = db
        return asyncio.run(run_cleanup(db, case.settings, case.gateway, request_ or req(case), **kwargs))


def posts(case, suffix):
    return [c for c in case.provider.calls if c[0] == "POST" and c[1].endswith(suffix)]


def snapshot(case):
    with SessionLocal() as db:
        b = case.rows[0]
        campaign = db.get(Campaign, case.campaign_id)
        decision = db.scalar(select(CampaignDecision).where(CampaignDecision.campaign_id == case.campaign_id))
        member = db.scalar(select(DecisionCohortMember).where(DecisionCohortMember.booking_id == b.id))
        booking = db.get(Booking, b.id)
        work = db.scalar(select(SettlementWork).where(SettlementWork.campaign_id == case.campaign_id))
        ops = {o.kind: o for o in db.scalars(select(PaymentOperation).where(PaymentOperation.booking_id == b.id))}
        events = list(db.scalars(select(BookingEvent).where(
            BookingEvent.booking_id == b.id, BookingEvent.kind == "OPERATOR_TEST_CLEANUP_REQUESTED")))
        return SimpleNamespace(
            campaign=campaign.status, booking=booking.state, decision=decision, member=member,
            work=None if work is None else SimpleNamespace(**{k: getattr(work, k) for k in (
                "purpose", "state", "version", "attempts", "claim_token", "lease_expires_at", "due_at")}),
            ops={k: SimpleNamespace(state=o.state, request_id=o.request_id, provider_resource_id=o.provider_resource_id,
                                    version=o.version) for k, o in ops.items()},
            events=events, intent=(decision.post_collection or {}).get(CLEANUP_INTENT_KEY),
        )


def rejected(case, code, request_=None, settings=None):
    before = snapshot(case)
    with pytest.raises(CleanupRejected) as error:
        request(case, request_, settings)
    assert error.value.code == code
    after = snapshot(case)
    assert (after.campaign, after.booking, after.intent, after.work, len(after.events)) == (
        before.campaign, before.booking, None, before.work, 0)


def test_eligible_cleanup_refunds_once_and_preserves_confirmation_history(settlement_case):
    case = confirmed(settlement_case)
    before = snapshot(case)
    assert before.campaign == "CONFIRMED" and before.booking == "PAID" and before.work.state == "DONE"
    with SessionLocal() as db:
        report = inspect_cleanup(db, case.settings, req(case))
    assert report["eligible"] and report["mode"] == "INITIAL"
    assert snapshot(case).campaign == "CONFIRMED" and not case.provider.refunds  # inspection wrote nothing

    out = cleanup(case)
    assert out["campaign_state"] == "CANCELLED" and out["booking_state"] == "REFUNDED" and out["work"]["state"] == "DONE"
    after = snapshot(case)
    assert after.work.state == "DONE" and after.work.purpose == CLEANUP_PURPOSE
    assert after.work.version > before.work.version and after.work.attempts == before.work.attempts + 1
    assert case.provider.refunds == {case.rows[0].id: "COMPLETED"}
    assert len(posts(case, "/capture")) == 1
    refund_posts = posts(case, "/refund")
    assert len(refund_posts) == 1 and refund_posts[0][2] == str(after.ops["REFUND"].request_id)
    assert after.ops["CAPTURE"].state == "SUCCEEDED" and after.ops["REFUND"].state == "SUCCEEDED"
    # Historical decision, terms, cohort, capture and confirmation evidence are intact.
    for field in ("id", "result", "reason", "evidence", "terms_id", "terms_version", "snapshot_hash", "attendance"):
        assert getattr(after.decision, field) == getattr(before.decision, field)
    assert {k: v for k, v in after.decision.post_collection.items() if k != CLEANUP_INTENT_KEY} == before.decision.post_collection
    assert after.member.capture_id == before.member.capture_id and after.member.capture_status == "COMPLETED"
    assert after.member.capture_observation == before.member.capture_observation
    assert after.member.refund_id == case.rows[0].refund_id and after.member.refund_status == "COMPLETED"
    assert after.intent["previous_campaign_status"] == "CONFIRMED" and after.intent["reason"] == REASON
    assert after.intent["confirmation_snapshot"]["post_collection"] == before.decision.post_collection
    assert after.intent["prior_work"]["state"] == "DONE" and len(after.events) == 1
    projection = state(case)
    assert projection["collected_minor"] == 100 and projection["refunded_minor"] == 100
    assert projection["net_collected_minor"] == 0 and projection["sandbox_cleanup"]["status"] == "REFUNDED"
    assert projection["sandbox_cleanup"]["previously_confirmed"] and not projection["review_required"]

    again = cleanup(case)
    assert again["claimed"] is False and again["campaign_state"] == "CANCELLED"
    assert len(posts(case, "/refund")) == 1 and len(posts(case, "/capture")) == 1
    assert len(snapshot(case).events) == 1


def test_ordinary_processing_cannot_reopen_confirmed_or_run_cleanup_work(settlement_case):
    case = confirmed(settlement_case)
    assert advance(case) == "CONFIRMED"
    with SessionLocal() as db:
        case.provider.local.db = db
        assert asyncio.run(process_due(db, case.settings, case.gateway, campaign_id=case.campaign_id)) == []
        with pytest.raises(HTTPException) as error:
            asyncio.run(BookingPaymentService(db, case.settings, case.gateway).cancel(case.rows[0].id))
        assert error.value.status_code == 409
    assert snapshot(case).campaign == "CONFIRMED" and not posts(case, "/refund")

    request(case)  # durable intent only; no provider call
    with SessionLocal() as db:
        case.provider.local.db = db
        assert claim_due(db, campaign_id=case.campaign_id) is None
        assert asyncio.run(process_due(db, case.settings, case.gateway, campaign_id=case.campaign_id)) == []
        with pytest.raises(ValueError):
            claim_due(db, purpose=CLEANUP_PURPOSE)  # cleanup claims must name the exact campaign
        db.rollback()
    after = snapshot(case)
    assert after.campaign == "COMPENSATING" and after.booking == "REFUND_PENDING"
    assert after.work.state == "READY" and not posts(case, "/refund")


def test_multi_booking_campaign_is_rejected(settlement_case):
    case = confirmed(settlement_case, n=2)
    rejected(case, "COHORT_NOT_SINGLE_BOOKING")
    with SessionLocal() as db:
        assert not inspect_cleanup(db, case.settings, req(case))["eligible"]


@pytest.mark.parametrize("change,code", [
    (lambda c: {"campaign_id": uuid.uuid4()}, "CAMPAIGN_NOT_FOUND"),
    (lambda c: {"booking_id": uuid.uuid4()}, "BOOKING_NOT_COHORT_MEMBER"),
    (lambda c: {"capture_id": "CAPTUREUNRELATED"}, "CAPTURE_NOT_BOOKING_CAPTURE"),
    (lambda c: {"capture_id": c.rows[0].auth_id}, "CAPTURE_NOT_BOOKING_CAPTURE"),
    (lambda c: {"capture_id": "bad id/../x"}, "EXACT_CAPTURE_ID_REQUIRED"),
    (lambda c: {"expected_amount_minor": 1000}, "EXPECTED_AMOUNT_NOT_SUPPORTED"),
    (lambda c: {"expected_amount_minor": 100.0}, "EXPECTED_AMOUNT_NOT_SUPPORTED"),
    (lambda c: {"expected_currency": "USD"}, "EXPECTED_CURRENCY_NOT_SUPPORTED"),
    (lambda c: {"action": "FORCE_CANCEL"}, "EXPLICIT_CLEANUP_ACTION_REQUIRED"),
    (lambda c: {"reason": "  short "}, "OPERATOR_TEST_REASON_REQUIRED"),
])
def test_mismatched_references_and_terms_are_rejected(settlement_case, change, code):
    case = confirmed(settlement_case)
    rejected(case, code, req(case, **change(case)))
    assert not posts(case, "/refund")


def test_other_campaign_with_this_booking_is_rejected(settlement_case):
    case, other = confirmed(settlement_case), confirmed(settlement_case)
    rejected(case, "BOOKING_NOT_COHORT_MEMBER", req(case, campaign_id=other.campaign_id))
    rejected(other, "BOOKING_NOT_COHORT_MEMBER", req(case, campaign_id=other.campaign_id))


def test_actual_amount_or_currency_mismatch_is_rejected(settlement_case):
    case = confirmed(settlement_case, price=200)
    rejected(case, "AMOUNT_OR_CURRENCY_MISMATCH")
    case = confirmed(settlement_case)
    with SessionLocal() as db:
        member = db.scalar(select(DecisionCohortMember).where(DecisionCohortMember.booking_id == case.rows[0].id))
        member.capture_observation = {**member.capture_observation, "currency": "USD"}
        db.commit()
    rejected(case, "AMOUNT_OR_CURRENCY_MISMATCH")


def test_non_sandbox_configuration_is_rejected(settlement_case):
    with pytest.raises(ValidationError):
        AppSettings(_env_file=None, paypal_env="live")
    case = confirmed(settlement_case)
    rejected(case, "SANDBOX_REQUIRED", settings=case.settings.model_copy(update={"paypal_env": "live"}))
    with SessionLocal() as db, pytest.raises(CleanupRejected) as error:
        asyncio.run(run_cleanup(db, case.settings, SimpleNamespace(_base_url="https://api-m.paypal.com"), req(case)))
    assert error.value.code == "SANDBOX_REQUIRED"
    with SessionLocal() as db, pytest.raises(CleanupRejected) as error:
        asyncio.run(run_cleanup(db, case.settings, None, req(case)))
    assert error.value.code == "NETWORK_NOT_PERMITTED"
    assert snapshot(case).campaign == "CONFIRMED" and not posts(case, "/refund")


def test_initial_request_then_idempotent_resume_without_confirmed_state(settlement_case):
    case = confirmed(settlement_case)
    before = snapshot(case)
    first = request(case)
    assert first["intent_created"] and first["campaign_state"] == "COMPENSATING"
    second = request(case)
    assert not second["intent_created"] and second["intent_requested_at"] == first["intent_requested_at"]
    mid = snapshot(case)
    assert mid.booking == "REFUND_PENDING" and len(mid.events) == 1
    assert mid.work.version == before.work.version + 1 and mid.work.state == "READY"
    with pytest.raises(CleanupRejected) as error:
        request(case, req(case, capture_id="CAPTUREOTHER"))
    assert error.value.code == "CLEANUP_IDENTITY_MISMATCH"
    with pytest.raises(CleanupRejected) as error:
        request(case, req(case, booking_id=uuid.uuid4()))
    assert error.value.code == "CLEANUP_IDENTITY_MISMATCH"
    resumed = cleanup(case, req(case, reason="A different but valid operator reason"))
    assert resumed["campaign_state"] == "CANCELLED" and not resumed["intent_created"]
    assert snapshot(case).intent["reason"] == REASON  # the original durable reason is kept


def test_concurrent_duplicate_requests_and_runners_resolve_to_one_cleanup(settlement_case):
    case = confirmed(settlement_case)
    before = snapshot(case)
    barrier, pids, lock = threading.Barrier(2), set(), threading.Lock()

    def requester(_):
        with engine.connect() as connection, SessionLocal(bind=connection) as db:
            pid = db.scalar(text("SELECT pg_backend_pid()"))
            db.commit()
            with lock:
                pids.add(pid)
            barrier.wait(timeout=10)
            return request_cleanup(db, case.settings, req(case))["intent_created"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        created = list(pool.map(requester, range(2)))
    assert len(pids) == 2 and sorted(created) == [False, True]
    mid = snapshot(case)
    assert len(mid.events) == 1 and mid.work.version == before.work.version + 1

    arrived, release = threading.Event(), threading.Event()

    def pause(_):
        arrived.set()
        assert release.wait(timeout=10)
    case.provider.before_refund = pause
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(cleanup, case)
        assert arrived.wait(timeout=10)
        try:
            # A duplicate runner during the in-flight refund cannot claim the active lease.
            duplicate = cleanup(case)
        finally:
            release.set()
        first = first.result(timeout=30)
    assert duplicate["claimed"] is False and first["campaign_state"] == "CANCELLED"
    assert len(posts(case, "/refund")) == 1 and len(posts(case, "/capture")) == 1


def test_active_work_lease_rejects_initial_cleanup(settlement_case):
    case = confirmed(settlement_case)
    with SessionLocal() as db:
        work = db.scalar(select(SettlementWork).where(SettlementWork.campaign_id == case.campaign_id))
        work.state, work.claim_token = "LEASED", uuid.uuid4()
        work.lease_expires_at = utcnow() + timedelta(minutes=2)
        db.commit()
    rejected(case, "WORK_LEASE_ACTIVE")
    with SessionLocal() as db:
        assert not inspect_cleanup(db, case.settings, req(case))["eligible"]


def test_rearm_fences_stale_workers_and_never_restarts_capture(settlement_case):
    case = confirmed(settlement_case)
    with SessionLocal() as db:
        enqueue(db, db.get(Campaign, case.campaign_id))  # an ordinary wakeup on a CONFIRMED campaign
        db.commit()
        stale = claim_due(db, campaign_id=case.campaign_id)
        assert stale is not None
        assert finish_work(db, stale) is True  # previous execution finishes; row READY, unleased
    request(case)
    with SessionLocal() as db:
        assert finish_work(db, stale, terminal=True) is False  # stale completion is fenced
        work = db.scalar(select(SettlementWork).where(SettlementWork.campaign_id == case.campaign_id))
        assert work.state == "READY" and work.purpose == CLEANUP_PURPOSE and work.version > stale.version
        db.commit()
    # The old capture path cannot be resumed, even by a retrieval-only claim.
    with SessionLocal() as db:
        service = SettlementService(db, case.settings, case.gateway)
        assert service._claim(case.campaign_id, case.rows[0].id, "CAPTURE") is None
    with engine.connect() as connection, SessionLocal(bind=connection) as db:
        case.provider.local.db = db
        assert asyncio.run(SettlementService(db, case.settings, case.gateway).advance(case.campaign_id)) == "CANCELLED"
    assert snapshot(case).ops["CAPTURE"].state == "SUCCEEDED"
    # A stale cleanup worker whose lease expired is fenced after takeover.
    case2 = confirmed(settlement_case)
    request(case2)
    with SessionLocal() as db:
        old = claim_due(db, campaign_id=case2.campaign_id, purpose=CLEANUP_PURPOSE)
        work = db.get(SettlementWork, old.id)
        work.lease_expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert cleanup(case2)["campaign_state"] == "CANCELLED"
    with SessionLocal() as db:
        assert finish_work(db, old, terminal=False) is False
        assert db.get(SettlementWork, old.id).state == "DONE"
    for c in (case, case2):
        assert len(posts(c, "/capture")) == 1 and len(posts(c, "/refund")) == 1


def test_pending_refund_is_processing_then_completes(settlement_case):
    case = confirmed(settlement_case)
    case.provider.pending_refund.add(case.rows[0].id)
    out = cleanup(case)
    assert out["campaign_state"] == "COMPENSATING" and out["booking_state"] == "REFUND_PENDING"
    assert out["refund_operation_state"] == "PROVIDER_PENDING" and out["work"]["state"] == "READY"
    projection = state(case)
    assert projection["sandbox_cleanup"]["status"] == "REFUND_PROCESSING"
    assert projection["refunded_minor"] == 0 and projection["collected_minor"] == 100
    case.provider.refunds[case.rows[0].id] = "COMPLETED"
    assert cleanup(case)["campaign_state"] == "CANCELLED"
    assert state(case)["sandbox_cleanup"]["status"] == "REFUNDED" and len(posts(case, "/refund")) == 1


@pytest.mark.parametrize("terminal", ["FAILED", "CANCELLED"])
def test_failed_or_cancelled_refund_requires_review_and_is_not_completed(settlement_case, terminal):
    case = confirmed(settlement_case)
    if terminal == "FAILED":
        case.provider.failed_refund.add(case.rows[0].id)
        cleanup(case)
    else:
        case.provider.pending_refund.add(case.rows[0].id)
        cleanup(case)
        case.provider.refunds[case.rows[0].id] = "CANCELLED"
        cleanup(case)
    for _ in range(2):
        out = cleanup(case)
        assert out["campaign_state"] == "COMPENSATING" and out["booking_state"] == "REFUND_PENDING"
        assert out["refund_operation_state"] == "DEFINITIVELY_FAILED"
    projection = state(case)
    assert projection["sandbox_cleanup"]["status"] == "REVIEW_REQUIRED" and projection["review_required"]
    assert projection["refunded_minor"] == 0
    after = snapshot(case)
    assert after.intent["review_reason"] == f"REFUND_{terminal}" and after.work.state != "DONE"
    assert len(posts(case, "/refund")) == 1 and len(posts(case, "/capture")) == 1


def test_timeout_then_restart_reconciles_known_refund_without_second_post(settlement_case):
    case = confirmed(settlement_case)
    case.provider.timeout_refund.add(case.rows[0].id)
    out = cleanup(case)
    assert out["campaign_state"] == "COMPENSATING" and out["refund_operation_state"] == "UNKNOWN"
    assert state(case)["sandbox_cleanup"]["status"] == "REVIEW_REQUIRED"
    assert snapshot(case).intent["review_reason"] == "REFUND_OUTCOME_UNKNOWN"
    assert cleanup(case)["campaign_state"] == "COMPENSATING"  # restart: retrieval-only, still unknown
    assert len(posts(case, "/refund")) == 1
    with pytest.raises(CleanupRejected):
        cleanup(case, known_refund_id="bad/../id")
    out = cleanup(case, known_refund_id=case.rows[0].refund_id)
    assert out["reference_recovered"] and out["campaign_state"] == "CANCELLED"
    after = snapshot(case)
    assert after.booking == "REFUNDED" and after.intent["review_reason"] is None
    assert [h["reason"] for h in after.intent["review_history"]] == ["REFUND_OUTCOME_UNKNOWN", None]
    assert len(posts(case, "/refund")) == 1 and state(case)["sandbox_cleanup"]["status"] == "REFUNDED"


def test_crash_after_provider_refund_success_before_persistence(settlement_case, monkeypatch):
    case = confirmed(settlement_case)
    original = case.gateway.refund_capture

    async def crash(*args, **kwargs):
        await original(*args, **kwargs)
        raise SimulatedWorkerDeath()
    monkeypatch.setattr(case.gateway, "refund_capture", crash)
    with pytest.raises(SimulatedWorkerDeath):
        cleanup(case)
    crashed = snapshot(case)
    assert crashed.ops["REFUND"].state == "IN_FLIGHT" and crashed.work.state == "LEASED"
    assert case.provider.refunds == {case.rows[0].id: "COMPLETED"}
    assert state(case)["sandbox_cleanup"]["status"] != "REFUNDED"
    assert cleanup(case)["claimed"] is False  # active leases are respected
    with SessionLocal() as db:
        db.execute(text("UPDATE payment_operations SET lease_expires_at = now() - interval '1 second' WHERE id = "
                        "(SELECT id FROM payment_operations WHERE booking_id = :b AND kind = 'REFUND')"),
                   {"b": case.rows[0].id})
        db.execute(text("UPDATE settlement_work SET lease_expires_at = now() - interval '1 second' "
                        "WHERE campaign_id = :c"), {"c": case.campaign_id})
        db.commit()
    out = cleanup(case)
    assert out["campaign_state"] == "COMPENSATING" and out["refund_operation_state"] == "UNKNOWN"
    assert state(case)["sandbox_cleanup"]["status"] == "REVIEW_REQUIRED"
    out = cleanup(case, known_refund_id=case.rows[0].refund_id)
    assert out["campaign_state"] == "CANCELLED" and out["booking_state"] == "REFUNDED"
    refund_posts = posts(case, "/refund")
    assert len(refund_posts) == 1 and refund_posts[0][2] == str(crashed.ops["REFUND"].request_id)
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(PaymentOperation).where(
            PaymentOperation.booking_id == case.rows[0].id, PaymentOperation.kind == "REFUND")) == 1


def test_host_and_guest_statuses_are_accurate(settlement_case, owned):
    case = confirmed(settlement_case)
    app = create_app(case.settings)
    guest_client, host_client = TestClient(app), TestClient(app)
    with SessionLocal() as db:
        booking = db.get(Booking, case.rows[0].id)
        guest = db.get(GuestSession, booking.guest_session_id)
        guest.token_hash = hash_token("offline-cleanup-guest-cookie")
        workshop = db.get(Workshop, case.workshop_id)
        login = "cleanup-" + uuid.uuid4().hex
        db.add(MerchantCredential(merchant_id=workshop.merchant_id, login_identifier=login,
                                  password_hash=hash_password("offline-password")))
        db.commit()
    guest_client.cookies.set("tipping_guest_session", "offline-cleanup-guest-cookie")
    assert login_client(host_client, login, "offline-password")[0] == 200

    def views():
        g = guest_client.get(f"/api/bookings/{case.rows[0].id}")
        h = host_client.get(f"/api/merchant/workshops/{case.workshop_id}")
        assert g.status_code == 200 and h.status_code == 200
        return g.json(), h.json()["campaign"]["settlement"]

    g, h = views()
    assert g["workshop_confirmed"] and g["sandbox_cleanup_status"] is None and h["sandbox_cleanup"] is None
    request(case)
    g, h = views()
    assert g["campaign_status"] == "COMPENSATING" and not g["workshop_confirmed"]
    assert g["state"] == "REFUND_PENDING" and g["sandbox_cleanup_status"] == "REFUND_PROCESSING"
    assert g["captured_minor"] == 100 and g["refunded_minor"] == 0 and not g["can_cancel"]
    assert "reason" not in g and REASON not in str(g)
    assert h["state"] == "COMPENSATING" and h["sandbox_cleanup"]["status"] == "REFUND_PROCESSING"
    assert h["sandbox_cleanup"]["previously_confirmed"] and h["sandbox_cleanup"]["reason"] == REASON
    assert (h["collected_minor"], h["refunded_minor"], h["net_collected_minor"]) == (100, 0, 100)
    cleanup(case)
    g, h = views()
    assert g["campaign_status"] == "CANCELLED" and g["state"] == "REFUNDED" and not g["workshop_confirmed"]
    assert g["sandbox_cleanup_status"] == "REFUNDED" and g["refunded_minor"] == 100
    assert h["sandbox_cleanup"]["status"] == "REFUNDED"
    assert (h["collected_minor"], h["refunded_minor"], h["net_collected_minor"]) == (100, 100, 0)
    for path in (f"/api/campaigns/{case.campaign_id}/cleanup", f"/api/campaigns/{case.campaign_id}/cancel"):
        assert TestClient(app).post(path, json={}).status_code in (404, 405)


def _fingerprint(excluded_campaigns):
    with SessionLocal() as db:
        excluded_bookings = select(Booking.id).where(Booking.campaign_id.in_(excluded_campaigns))
        return (
            sorted(db.execute(text("SELECT id::text, name FROM merchants")).all()),
            sorted(db.execute(select(Campaign.id, Campaign.status, Campaign.updated_at)
                              .where(Campaign.id.notin_(excluded_campaigns))).all()),
            sorted(db.execute(select(SettlementWork.id, SettlementWork.purpose, SettlementWork.state,
                                     SettlementWork.version, SettlementWork.attempts, SettlementWork.due_at,
                                     SettlementWork.claim_token)
                              .where(SettlementWork.campaign_id.notin_(excluded_campaigns))).all()),
            sorted(db.execute(select(PaymentOperation.id, PaymentOperation.state, PaymentOperation.version)
                              .where(PaymentOperation.booking_id.notin_(excluded_bookings))).all()),
            sorted(db.execute(select(CampaignDecision.id, CampaignDecision.updated_at)
                              .where(CampaignDecision.campaign_id.notin_(excluded_campaigns))).all()),
            sorted(db.execute(select(Booking.id, Booking.state, Booking.updated_at)
                              .where(Booking.campaign_id.notin_(excluded_campaigns))).all()),
        )


def test_unrelated_ready_deadline_work_sentinel_and_records_are_untouched(settlement_case):
    other = settlement_case(n=1, price=100)  # OPEN and past cutoff: due DEADLINE work
    with SessionLocal() as db:
        discover_due(db, campaign_id=other.campaign_id)
        work = db.scalar(select(SettlementWork).where(SettlementWork.campaign_id == other.campaign_id))
        assert (work.purpose, work.state) == ("DEADLINE", "READY")
        sentinel = db.scalar(select(func.count()).select_from(Merchant).where(Merchant.name.like("SENTINEL%")))
    case = confirmed(settlement_case)
    before = _fingerprint([case.campaign_id])
    cleanup(case)
    request(case)
    assert _fingerprint([case.campaign_id]) == before
    with SessionLocal() as db:
        work = db.scalar(select(SettlementWork).where(SettlementWork.campaign_id == other.campaign_id))
        assert (work.purpose, work.state, work.attempts, work.claim_token) == ("DEADLINE", "READY", 0, None)
        assert db.get(Campaign, other.campaign_id).status == "OPEN"
        assert db.scalar(select(CampaignDecision.id).where(CampaignDecision.campaign_id == other.campaign_id)) is None
        assert db.scalar(select(func.count()).select_from(Merchant).where(Merchant.name.like("SENTINEL%"))) == sentinel
    assert not [c for c in other.provider.calls]
    assert snapshot(case).campaign == "CANCELLED"


SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "process_settlement_work.py"


def _cli(*argv):
    module = runpy.run_path(str(SCRIPT), run_name="cleanup_cli_test")
    return asyncio.run(module["run"](module["parser"]().parse_args(list(argv))))


def test_operator_cli_inspects_by_default_and_requires_exact_scoped_arguments(settlement_case, capsys):
    case = confirmed(settlement_case)
    b = case.rows[0]
    exact = ["--sandbox-test-cleanup", "--campaign-id", str(case.campaign_id), "--booking-id", str(b.id),
             "--capture-id", b.capture_id, "--expected-amount-minor", "100", "--expected-currency", "GBP",
             "--reason", REASON]
    _cli(*exact)
    assert '"eligible": true' in capsys.readouterr().out
    assert snapshot(case).campaign == "CONFIRMED" and snapshot(case).intent is None
    for argv, message in (
        (exact[:-2], "--reason"),
        ([*exact, "--known-capture-id", b.capture_id], "refund-only"),
        ([*exact, "--known-refund-id", b.refund_id], "--execute --allow-network"),
        ([*exact, "--allow-network"], "requires --execute"),
        (exact[1:], "--sandbox-test-cleanup"),
    ):
        with pytest.raises(SystemExit) as error:
            _cli(*argv)
        assert message in str(error.value)
    _cli(*exact[:-1], "short")  # inspection reports rejection without writing
    assert '"rejection": "OPERATOR_TEST_REASON_REQUIRED"' in capsys.readouterr().out
    with pytest.raises(SystemExit) as error:
        _cli(*exact[:7], "--expected-amount-minor", "1000", *exact[9:], "--execute")
    assert "EXPECTED_AMOUNT_NOT_SUPPORTED" in str(error.value)
    assert snapshot(case).campaign == "CONFIRMED"
    _cli(*exact, "--execute")  # durable intent only; provider calls not permitted
    assert '"provider_calls": "not permitted"' in capsys.readouterr().out
    after = snapshot(case)
    assert after.campaign == "COMPENSATING" and after.intent is not None and not posts(case, "/refund")
