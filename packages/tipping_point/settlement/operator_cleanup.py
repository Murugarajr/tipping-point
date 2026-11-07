"""Sandbox-only operator cleanup of one confirmed single-booking test campaign.

Approved exception (2026-11-07), and nothing broader:

    Campaign: CONFIRMED -> COMPENSATING -> CANCELLED
    Booking:  PAID -> REFUND_PENDING -> REFUNDED

Only for an operator-selected PayPal Sandbox test campaign whose frozen cohort
holds exactly one booking with exactly one verified, completed GBP 1.00
capture. Ordinary settlement processing never reopens CONFIRMED. This is not
an attendee-refund policy, a public cancellation feature, or a force option.

The refund itself reuses the existing durable ledger: ``SettlementService``
claims the logical REFUND operation (immutable payload/hash, request UUID,
lease and version fencing), calls the provider outside any transaction, and
reconciles unknown outcomes by retrieval only. Historical decision, terms,
cohort, capture references and confirmation evidence are preserved; the
cleanup intent is added beside them, never written over them.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import uuid

from sqlalchemy import select

from ..db.models import (
    Booking, BookingEvent, Campaign, CampaignDecision, DecisionCohortMember, PaymentOperation, SettlementWork,
)
from ..guest.service import utcnow
from ..paypal.client import PAYPAL_SANDBOX_BASE_URL
from .decision import CLEANUP_INTENT_KEY, CLEANUP_PURPOSE, cleanup_intent, enqueue

ACTION = "SANDBOX_TEST_CAMPAIGN_CLEANUP"
EXPECTED_AMOUNT_MINOR = 100
EXPECTED_CURRENCY = "GBP"
UNRESOLVED = ("PREPARED", "IN_FLIGHT", "UNKNOWN", "PROVIDER_PENDING")
OTHER_BOOKING_TERMINAL = ("VOIDED", "CANCELLED", "EXPIRED")
RESUMABLE_CAMPAIGN_STATES = ("COMPENSATING", "ABORTING", "CANCELLED")
_PROVIDER_ID = re.compile(r"^[A-Za-z0-9-]{1,100}$")


class CleanupRejected(ValueError):
    """Eligibility failure; ``code`` is a stable, non-sensitive identifier."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class CleanupRequest:
    campaign_id: uuid.UUID
    booking_id: uuid.UUID
    capture_id: str
    expected_amount_minor: int
    expected_currency: str
    reason: str
    action: str

    def validate_shape(self) -> None:
        if self.action != ACTION:
            raise CleanupRejected("EXPLICIT_CLEANUP_ACTION_REQUIRED")
        if not isinstance(self.campaign_id, uuid.UUID) or not isinstance(self.booking_id, uuid.UUID):
            raise CleanupRejected("EXACT_IDENTIFIERS_REQUIRED")
        if not isinstance(self.capture_id, str) or not _PROVIDER_ID.fullmatch(self.capture_id):
            raise CleanupRejected("EXACT_CAPTURE_ID_REQUIRED")
        if type(self.expected_amount_minor) is not int or self.expected_amount_minor != EXPECTED_AMOUNT_MINOR:
            raise CleanupRejected("EXPECTED_AMOUNT_NOT_SUPPORTED")
        if self.expected_currency != EXPECTED_CURRENCY:
            raise CleanupRejected("EXPECTED_CURRENCY_NOT_SUPPORTED")
        reason = self.reason.strip() if isinstance(self.reason, str) else ""
        if not 10 <= len(reason) <= 200 or not reason.isprintable():
            raise CleanupRejected("OPERATOR_TEST_REASON_REQUIRED")


def require_sandbox(settings, gateway=None) -> None:
    """Effective provider environment must be Sandbox for configuration and transport."""
    if getattr(settings, "paypal_env", None) != "sandbox":
        raise CleanupRejected("SANDBOX_REQUIRED")
    if gateway is not None and getattr(gateway, "_base_url", None) != PAYPAL_SANDBOX_BASE_URL:
        raise CleanupRejected("SANDBOX_REQUIRED")


@dataclass
class _Loaded:
    campaign: Campaign | None
    decision: CampaignDecision | None
    members: list
    bookings: list
    operations: list
    work: SettlementWork | None


def _load(db, campaign_id, *, lock: bool) -> _Loaded:
    """Campaign -> bookings -> work lock order matches the existing settlement paths."""
    query = select(Campaign).where(Campaign.id == campaign_id).execution_options(populate_existing=True)
    campaign = db.scalar(query.with_for_update() if lock else query)
    if campaign is None:
        return _Loaded(None, None, [], [], [], None)
    decision = db.scalar(select(CampaignDecision).where(CampaignDecision.campaign_id == campaign_id)
                         .execution_options(populate_existing=True))
    members = list(db.scalars(select(DecisionCohortMember).where(
        DecisionCohortMember.decision_id == decision.id).order_by(DecisionCohortMember.booking_id)
        .execution_options(populate_existing=True))) if decision else []
    query = select(Booking).where(Booking.campaign_id == campaign_id).order_by(Booking.id).execution_options(
        populate_existing=True)
    bookings = list(db.scalars(query.with_for_update() if lock else query))
    operations = list(db.scalars(select(PaymentOperation).where(
        PaymentOperation.booking_id.in_([b.id for b in bookings])).execution_options(populate_existing=True)))
    query = select(SettlementWork).where(SettlementWork.campaign_id == campaign_id).execution_options(
        populate_existing=True)
    work = db.scalar(query.with_for_update() if lock else query)
    return _Loaded(campaign, decision, members, bookings, operations, work)


def _single_member(loaded: _Loaded, request: CleanupRequest):
    decision = loaded.decision
    if decision is None:
        raise CleanupRejected("NO_FROZEN_DECISION")
    cohort_ids = list((decision.evidence or {}).get("cohort_booking_ids") or [])
    if len(loaded.members) != 1 or decision.attendance != 1 or len(cohort_ids) != 1:
        raise CleanupRejected("COHORT_NOT_SINGLE_BOOKING")
    member = loaded.members[0]
    if cohort_ids != [str(member.booking_id)]:
        raise CleanupRejected("FROZEN_COHORT_MISMATCH")
    if member.booking_id != request.booking_id:
        raise CleanupRejected("BOOKING_NOT_COHORT_MEMBER")
    booking = next((b for b in loaded.bookings if b.id == member.booking_id), None)
    if booking is None:
        raise CleanupRejected("BOOKING_NOT_IN_CAMPAIGN")
    if member.capture_id != request.capture_id:
        raise CleanupRejected("CAPTURE_NOT_BOOKING_CAPTURE")
    if (member.amount_minor != request.expected_amount_minor or member.currency != request.expected_currency
            or booking.amount_minor != request.expected_amount_minor or booking.currency != request.expected_currency):
        raise CleanupRejected("AMOUNT_OR_CURRENCY_MISMATCH")
    return member, booking


def _validate_initial(loaded: _Loaded, request: CleanupRequest):
    if loaded.campaign is None:
        raise CleanupRejected("CAMPAIGN_NOT_FOUND")
    if loaded.campaign.status != "CONFIRMED":
        raise CleanupRejected("CAMPAIGN_NOT_CONFIRMED")
    decision = loaded.decision
    if decision is None or decision.result != "COLLECT" or decision.review_required:
        raise CleanupRejected("DECISION_NOT_ELIGIBLE")
    member, booking = _single_member(loaded, request)
    if booking.state != "PAID" or booking.cancelled_at is not None:
        raise CleanupRejected("BOOKING_NOT_PAID")
    observation = member.capture_observation or {}
    if member.capture_status != "COMPLETED" or observation.get("status") != "COMPLETED":
        raise CleanupRejected("CAPTURE_NOT_VERIFIED_COMPLETED")
    if (observation.get("amount_minor") != request.expected_amount_minor
            or observation.get("currency") != request.expected_currency):
        raise CleanupRejected("AMOUNT_OR_CURRENCY_MISMATCH")
    if member.refund_id is not None or member.refund_status is not None:
        raise CleanupRejected("REFUND_ALREADY_PRESENT")
    own = [o for o in loaded.operations if o.booking_id == booking.id]
    captures = [o for o in own if o.kind == "CAPTURE"]
    if (len(captures) != 1 or captures[0].state != "SUCCEEDED"
            or captures[0].provider_resource_id != request.capture_id
            or captures[0].resource_scope != member.authorization_id):
        raise CleanupRejected("CAPTURE_LEDGER_MISMATCH")
    if any(o.kind == "REFUND" for o in own):
        raise CleanupRejected("REFUND_ALREADY_PRESENT")
    if any(o.state in UNRESOLVED for o in loaded.operations):
        raise CleanupRejected("CONFLICTING_OPERATION_UNRESOLVED")
    for other in loaded.bookings:
        if other.id == booking.id:
            continue
        if other.state not in OTHER_BOOKING_TERMINAL or any(
                o.booking_id == other.id and o.kind in ("CAPTURE", "REFUND") for o in loaded.operations):
            raise CleanupRejected("UNRELATED_BOOKING_UNRESOLVED")
    if loaded.work is not None and (loaded.work.state == "LEASED" or loaded.work.claim_token is not None):
        raise CleanupRejected("WORK_LEASE_ACTIVE")
    return member, booking


def _validate_resume(loaded: _Loaded, request: CleanupRequest, intent: dict):
    expected = {
        "action": request.action, "campaign_id": str(request.campaign_id),
        "booking_id": str(request.booking_id), "capture_id": request.capture_id,
        "amount_minor": request.expected_amount_minor, "currency": request.expected_currency,
    }
    if any(intent.get(key) != value for key, value in expected.items()):
        raise CleanupRejected("CLEANUP_IDENTITY_MISMATCH")
    if loaded.campaign.status not in RESUMABLE_CAMPAIGN_STATES:
        raise CleanupRejected("CLEANUP_STATE_INCONSISTENT")
    return _single_member(loaded, request)


def _iso(value):
    return value.isoformat() if value is not None else None


def _summary(loaded: _Loaded, *, created: bool, intent: dict | None) -> dict:
    member = loaded.members[0] if len(loaded.members) == 1 else None
    booking = next((b for b in loaded.bookings if member and b.id == member.booking_id), None)
    refund = next((o for o in loaded.operations if member and o.booking_id == member.booking_id
                   and o.kind == "REFUND"), None)
    return {
        "campaign_id": str(loaded.campaign.id), "campaign_state": loaded.campaign.status,
        "booking_state": booking.state if booking else None,
        "refund_operation_state": refund.state if refund else None,
        "refund_status": member.refund_status if member else None,
        "intent_created": created, "intent_requested_at": intent.get("requested_at") if intent else None,
        "work": None if loaded.work is None else {
            "purpose": loaded.work.purpose, "state": loaded.work.state, "version": loaded.work.version,
        },
    }


def inspect_cleanup(db, settings, request: CleanupRequest) -> dict:
    """Read-only eligibility report: no locks, no writes, no provider calls."""
    try:
        require_sandbox(settings)
        request.validate_shape()
        loaded = _load(db, request.campaign_id, lock=False)
        if loaded.campaign is None:
            raise CleanupRejected("CAMPAIGN_NOT_FOUND")
        intent = cleanup_intent(loaded.decision)
        if intent:
            _validate_resume(loaded, request, intent)
            mode = "RESUME"
        else:
            _validate_initial(loaded, request)
            mode = "INITIAL"
        return {"eligible": True, "mode": mode, **_summary(loaded, created=False, intent=intent)}
    except CleanupRejected as error:
        return {"eligible": False, "rejection": error.code}
    finally:
        db.rollback()


def request_cleanup(db, settings, request: CleanupRequest) -> dict:
    """Persist intent, audit and re-armed work in one short campaign-locked transaction.

    Concurrent/repeated requests serialize on the campaign lock and the later
    ones observe the committed intent and resume it; there is never a second
    logical cleanup. No provider call happens here.
    """
    require_sandbox(settings)
    request.validate_shape()
    try:
        loaded = _load(db, request.campaign_id, lock=True)
        if loaded.campaign is None:
            raise CleanupRejected("CAMPAIGN_NOT_FOUND")
        intent = cleanup_intent(loaded.decision)
        if intent:
            _validate_resume(loaded, request, intent)
            summary = _summary(loaded, created=False, intent=intent)
            db.commit()
            return summary
        member, booking = _validate_initial(loaded, request)
    except Exception:
        db.rollback()
        raise
    campaign, decision, now = loaded.campaign, loaded.decision, utcnow()
    work = loaded.work
    prior_work = None if work is None else {
        "purpose": work.purpose, "state": work.state, "version": work.version,
        "attempts": work.attempts, "last_error": work.last_error, "due_at": _iso(work.due_at),
    }
    if work is None:
        work = enqueue(db, campaign, purpose=CLEANUP_PURPOSE, due_at=now)
        db.flush()
    else:
        # Guarded re-arm of the single per-campaign row. The version bump fences
        # every earlier claim; the cleared token makes stale finish_work a no-op.
        work.version += 1
        work.purpose = CLEANUP_PURPOSE
        work.state = "READY"
        work.due_at = now
        work.claim_token = None
        work.lease_expires_at = None
        work.last_error = None
    previous_post_collection = dict(decision.post_collection or {})
    intent = {
        "action": ACTION, "environment": "sandbox",
        "campaign_id": str(campaign.id), "booking_id": str(booking.id), "capture_id": member.capture_id,
        "amount_minor": member.amount_minor, "currency": member.currency,
        "reason": request.reason.strip(), "requested_at": now.isoformat(),
        "previous_campaign_status": campaign.status, "previous_booking_state": booking.state,
        "confirmation_snapshot": {
            "decision_id": str(decision.id), "decision_result": decision.result,
            "decision_reason": decision.reason, "terms_id": str(decision.terms_id),
            "terms_version": decision.terms_version, "snapshot_hash": decision.snapshot_hash,
            "post_collection": previous_post_collection,
            "capture_observation": dict(member.capture_observation or {}),
        },
        "prior_work": prior_work, "rearmed_work_version": work.version,
        "review_reason": None, "review_history": [],
    }
    decision.post_collection = {**previous_post_collection, CLEANUP_INTENT_KEY: intent}
    campaign.status = "COMPENSATING"
    booking.state = "REFUND_PENDING"
    db.add(BookingEvent(booking_id=booking.id, kind="OPERATOR_TEST_CLEANUP_REQUESTED", details={
        "action": ACTION, "reason": intent["reason"], "capture_id": member.capture_id,
        "amount_minor": member.amount_minor, "currency": member.currency,
        "previous_campaign_status": intent["previous_campaign_status"],
        "previous_booking_state": intent["previous_booking_state"],
        "prior_work": prior_work, "rearmed_work_version": work.version,
    }))
    db.commit()
    summary = _summary(_load(db, request.campaign_id, lock=False), created=True, intent=intent)
    db.commit()
    return summary


def _review_reason(member, booking, refund_operation):
    if member.refund_status in ("FAILED", "CANCELLED"):
        return f"REFUND_{member.refund_status}"
    if refund_operation is not None and refund_operation.state == "UNKNOWN":
        return "REFUND_OUTCOME_UNKNOWN"
    if refund_operation is not None and refund_operation.state == "DEFINITIVELY_FAILED":
        return "REFUND_NOT_COMPLETED"
    if booking.state == "REVIEW_REQUIRED":
        return "BOOKING_REVIEW_REQUIRED"
    return None


def _persist_review_reason(db, campaign_id) -> None:
    """Durably record why cleanup needs review; resolved reasons stay in history."""
    loaded = _load(db, campaign_id, lock=True)
    intent = cleanup_intent(loaded.decision)
    if not intent or len(loaded.members) != 1:
        db.commit()
        return
    member = loaded.members[0]
    booking = next(b for b in loaded.bookings if b.id == member.booking_id)
    refund = next((o for o in loaded.operations if o.booking_id == member.booking_id and o.kind == "REFUND"), None)
    reason = _review_reason(member, booking, refund)
    if reason != intent.get("review_reason"):
        history = list(intent.get("review_history") or [])
        history.append({"reason": reason, "observed_at": utcnow().isoformat()})
        loaded.decision.post_collection = {
            **loaded.decision.post_collection,
            CLEANUP_INTENT_KEY: {**intent, "review_reason": reason, "review_history": history},
        }
    db.commit()


async def run_cleanup(db, settings, gateway, request: CleanupRequest, *, known_refund_id: str | None = None) -> dict:
    """Exact-campaign cleanup pass. Never claims other campaigns or generic work."""
    from .dispatch import claim_due, finish_work
    from .service import SettlementService

    require_sandbox(settings, gateway)
    if gateway is None:
        raise CleanupRejected("NETWORK_NOT_PERMITTED")
    if known_refund_id is not None and not _PROVIDER_ID.fullmatch(known_refund_id):
        raise CleanupRejected("EXACT_REFUND_ID_REQUIRED")
    summary = request_cleanup(db, settings, request)  # revalidates at execution time
    # The explicit operator run makes only this campaign's idle cleanup row due now.
    # Leased rows are left to their lease; other campaigns and purposes are never touched.
    work = db.scalar(select(SettlementWork).where(
        SettlementWork.campaign_id == request.campaign_id, SettlementWork.purpose == CLEANUP_PURPOSE,
        SettlementWork.state == "READY").with_for_update().execution_options(populate_existing=True))
    if work is not None and work.due_at > utcnow():
        work.due_at = utcnow()
    db.commit()
    claim = claim_due(db, campaign_id=request.campaign_id, purpose=CLEANUP_PURPOSE)
    if claim is None:
        return {**summary, "claimed": False, "note": "cleanup work is leased elsewhere, not yet due, or finished"}
    result = {"claimed": True}
    try:
        service = SettlementService(db, settings, gateway)
        if known_refund_id is not None:
            result["reference_recovered"] = await service.recover_reference(
                request.campaign_id, request.booking_id, "REFUND", known_refund_id)
        state = await service.advance(request.campaign_id)
        _persist_review_reason(db, request.campaign_id)
        pending = db.scalar(select(PaymentOperation.id).join(Booking).where(
            Booking.campaign_id == request.campaign_id,
            PaymentOperation.state.in_(("IN_FLIGHT", "UNKNOWN", "PROVIDER_PENDING")),
        ).limit(1))
        db.commit()
        # True only when this claim's fence still held; the row's DONE/READY state is in "work".
        result["work_claim_fenced"] = finish_work(db, claim, terminal=state == "CANCELLED" and pending is None)
    except Exception as error:
        db.rollback()
        finish_work(db, claim, error=type(error).__name__)
        result["error"] = type(error).__name__
    loaded = _load(db, request.campaign_id, lock=False)
    out = {**_summary(loaded, created=summary["intent_created"], intent=cleanup_intent(loaded.decision)), **result}
    db.rollback()
    return out


def cleanup_presentation(campaign, decision, member, booking, refund_operation):
    """Honest status: completion only after a verified full refund and CANCELLED campaign."""
    intent = cleanup_intent(decision)
    if not intent or member is None or booking is None:
        return None
    completed = (
        campaign.status == "CANCELLED" and booking.state == "REFUNDED"
        and member.refund_status == "COMPLETED"
        and refund_operation is not None and refund_operation.state == "SUCCEEDED"
    )
    review = not completed and (
        bool(decision.review_required) or booking.state == "REVIEW_REQUIRED"
        or member.refund_status in ("FAILED", "CANCELLED")
        or (refund_operation is not None and refund_operation.state in ("UNKNOWN", "DEFINITIVELY_FAILED"))
    )
    return {
        "status": "REFUNDED" if completed else "REVIEW_REQUIRED" if review else "REFUND_PROCESSING",
        "reason": intent.get("reason"), "requested_at": intent.get("requested_at"),
        "previously_confirmed": intent.get("previous_campaign_status") == "CONFIRMED",
        "review_reason": intent.get("review_reason"),
    }
