"""Retrieval-only recovery of a completed cleanup refund left UNKNOWN by the link-host parser defect.

Real PostgreSQL (tipping_point_test via testguard) and MockTransport only. The stuck
state is produced through the actual cleanup path: the provider returns refund links
on ``api.sandbox.paypal.com`` (as PayPal Sandbox did on 2026-11-07) while the
pre-fix parse allowlist (``api-m`` only) is patched in for that first run.
"""

import uuid

import pytest
from sqlalchemy import func, select

from tipping_point.db.models import BookingEvent, CampaignDecision, PaymentOperation
from tipping_point.db.session import SessionLocal
from tipping_point.paypal import client as paypal_client
from tipping_point.settlement.decision import CLEANUP_INTENT_KEY, CLEANUP_PURPOSE
from .test_sandbox_cleanup import cleanup, confirmed, posts, snapshot
from .test_settlement import settlement_case, state  # noqa: F401

LEGACY_HOST = "api.sandbox.paypal.com"


def legacy_links(case, *, capture_for=None):
    original = case.provider.refund

    def refund(b):
        body = original(b)
        target = capture_for(b) if capture_for else b.capture_id
        body["links"] = [
            {"rel": "self", "method": "GET", "href": f"https://{LEGACY_HOST}/v2/payments/refunds/{b.refund_id}"},
            {"rel": "up", "method": "GET", "href": f"https://{LEGACY_HOST}/v2/payments/captures/{target}"},
        ]
        return body
    case.provider.refund = refund


def refund_op(case):
    with SessionLocal() as db:
        ops = list(db.scalars(select(PaymentOperation).where(
            PaymentOperation.booking_id == case.rows[0].id, PaymentOperation.kind == "REFUND")))
        assert len(ops) == 1, "exactly one logical refund operation"
        o = ops[0]
        return {"id": o.id, "request_id": o.request_id, "request_payload": dict(o.request_payload),
                "request_hash": o.request_hash, "resource_scope": o.resource_scope,
                "provider_resource_id": o.provider_resource_id, "state": o.state, "error_code": o.error_code,
                "claim_token": o.claim_token}


def events(case, kind):
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(BookingEvent).where(
            BookingEvent.booking_id == case.rows[0].id, BookingEvent.kind == kind))


def stuck_like_development(settlement_case, monkeypatch):
    """Reproduce the exact persisted development state through the real code path."""
    case = confirmed(settlement_case)
    legacy_links(case)
    with monkeypatch.context() as m:
        m.setattr(paypal_client, "PAYPAL_SANDBOX_LINK_HOSTS", frozenset({"api-m.sandbox.paypal.com"}))
        out = cleanup(case)
    assert out["refund_operation_state"] == "UNKNOWN" and out["work_claim_fenced"] is True
    s = snapshot(case)
    op = refund_op(case)
    assert (s.campaign, s.booking) == ("COMPENSATING", "REFUND_PENDING")
    assert op["state"] == "UNKNOWN" and op["error_code"] == "ValueError"
    assert op["provider_resource_id"] == case.rows[0].refund_id == s.member.refund_id  # refund ID saved
    assert s.member.refund_status is None and s.decision.review_required
    assert s.intent["review_reason"] == "REFUND_OUTCOME_UNKNOWN"
    assert s.work.purpose == CLEANUP_PURPOSE and s.work.state == "READY" and s.work.claim_token is None
    assert case.provider.refunds == {case.rows[0].id: "COMPLETED"}  # money moved exactly once
    assert len(posts(case, "/refund")) == 1 and events(case, "SETTLEMENT_ERROR") == 1
    return case, s, op


def financial_calls(case, since):
    return [c for c in case.provider.calls[since:] if c[1] != "/v1/oauth2/token"]


def test_recovery_is_retrieval_only_and_completes_cleanup(settlement_case, monkeypatch):
    case, before, op_before = stuck_like_development(settlement_case, monkeypatch)
    b = case.rows[0]
    mark = len(case.provider.calls)

    out = cleanup(case)  # the same scoped operator command path, no known-refund flag

    calls = financial_calls(case, mark)
    assert calls and all(method == "GET" for method, _path, _rid in calls), calls
    assert ("GET", f"/v2/payments/refunds/{b.refund_id}", None) in calls
    assert not [c for c in calls if c[1].endswith(("/refund", "/capture", "/void"))]
    assert len(posts(case, "/refund")) == 1 and len(posts(case, "/capture")) == 1 and not case.provider.voided

    op = refund_op(case)  # same logical operation, identity and payload untouched
    for key in ("id", "request_id", "request_payload", "request_hash", "resource_scope", "provider_resource_id"):
        assert op[key] == op_before[key], key
    assert op["state"] == "SUCCEEDED" and op["error_code"] is None and op["claim_token"] is not None

    after = snapshot(case)
    assert out["campaign_state"] == after.campaign == "CANCELLED"
    assert out["booking_state"] == after.booking == "REFUNDED"
    assert after.member.refund_status == "COMPLETED" and after.member.refund_id == b.refund_id
    assert after.work.state == "DONE" and after.work.claim_token is None and after.work.lease_expires_at is None
    # Review: the only cause was this operation's UNKNOWN outcome; normal finalize derives it clear.
    assert not after.decision.review_required and after.intent["review_reason"] is None
    assert [h["reason"] for h in after.intent["review_history"]] == ["REFUND_OUTCOME_UNKNOWN", None]
    assert events(case, "SETTLEMENT_ERROR") == 1  # historical error evidence preserved
    # Original capture and confirmation evidence preserved.
    assert after.member.capture_id == before.member.capture_id and after.member.capture_status == "COMPLETED"
    assert after.member.capture_observation == before.member.capture_observation
    assert after.intent["confirmation_snapshot"] == before.intent["confirmation_snapshot"]
    for field in ("id", "result", "reason", "evidence", "terms_id", "snapshot_hash", "attendance"):
        assert getattr(after.decision, field) == getattr(before.decision, field)
    projection = state(case)
    assert projection["collected_minor"] == 100 and projection["refunded_minor"] == 100
    assert projection["net_collected_minor"] == 0 and projection["sandbox_cleanup"]["status"] == "REFUNDED"

    # Repeating recovery is a no-op: no provider traffic, no state change.
    mark = len(case.provider.calls)
    again = cleanup(case)
    assert again["claimed"] is False and financial_calls(case, mark) == []
    assert refund_op(case) == op and snapshot(case).campaign == "CANCELLED"


def test_recovery_marks_refunded_only_after_verified_completed(settlement_case, monkeypatch):
    case, _before, op_before = stuck_like_development(settlement_case, monkeypatch)
    b = case.rows[0]
    case.provider.refunds[b.id] = "PENDING"  # provider still settling the known refund
    mark = len(case.provider.calls)
    out = cleanup(case)
    assert all(c[0] == "GET" for c in financial_calls(case, mark))
    s = snapshot(case)
    assert (s.campaign, s.booking, refund_op(case)["state"]) == ("COMPENSATING", "REFUND_PENDING", "PROVIDER_PENDING")
    assert s.member.refund_status == "PENDING" and out["work"]["state"] == "READY" and s.work.claim_token is None
    assert state(case)["sandbox_cleanup"]["status"] != "REFUNDED"

    case.provider.refunds[b.id] = "COMPLETED"
    cleanup(case)
    s = snapshot(case)
    assert (s.campaign, s.booking, s.work.state) == ("CANCELLED", "REFUNDED", "DONE")
    assert refund_op(case)["request_id"] == op_before["request_id"] and len(posts(case, "/refund")) == 1


def test_recovery_still_rejects_a_refund_linked_to_another_capture(settlement_case, monkeypatch):
    case, _before, op_before = stuck_like_development(settlement_case, monkeypatch)
    legacy_links(case, capture_for=lambda b: "FOREIGNCAPTURE")  # well-formed, permitted host, wrong capture
    mark = len(case.provider.calls)
    cleanup(case)
    assert all(c[0] == "GET" for c in financial_calls(case, mark)) and len(posts(case, "/refund")) == 1
    s = snapshot(case)
    op = refund_op(case)
    assert op["state"] == "UNKNOWN" and op["request_id"] == op_before["request_id"]
    assert (s.campaign, s.booking) == ("COMPENSATING", "REFUND_PENDING")
    assert s.member.refund_status is None and s.decision.review_required
    assert s.intent["review_reason"] == "REFUND_OUTCOME_UNKNOWN"


def test_independent_review_cause_survives_recovered_refund(settlement_case, monkeypatch):
    case, _before, _op = stuck_like_development(settlement_case, monkeypatch)
    with SessionLocal() as db:  # an unrelated unresolved operation on the same campaign
        db.add(PaymentOperation(booking_id=case.rows[0].id, kind="VOID", resource_scope="INDEPENDENT",
                                request_id=uuid.uuid4(), request_payload={"independent": True},
                                request_hash="0" * 64, state="UNKNOWN"))
        db.commit()
    mark = len(case.provider.calls)
    cleanup(case)
    assert all(c[0] == "GET" for c in financial_calls(case, mark)) and not case.provider.voided
    s = snapshot(case)
    assert refund_op(case)["state"] == "SUCCEEDED" and s.booking == "REFUNDED"
    assert s.decision.review_required and s.campaign == "COMPENSATING"  # not cleared, not cancelled
    assert state(case)["sandbox_cleanup"]["status"] == "REVIEW_REQUIRED"
    with SessionLocal() as db:
        assert db.scalar(select(CampaignDecision.review_required).where(
            CampaignDecision.campaign_id == case.campaign_id)) is True
    assert CLEANUP_INTENT_KEY in s.decision.post_collection
