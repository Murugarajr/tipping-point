"""Short, campaign-first transactions for immutable deadline decisions."""

from dataclasses import asdict
from datetime import timedelta

from sqlalchemy import select, text

from ..db.models import Booking, Campaign, CampaignDecision, CampaignTerms, DecisionCohortMember, PaymentOperation, SettlementWork
from ..economics import CampaignFinancialsInput, build_snapshot_hash, calculate_viability
from ..economics.calculator import ALGORITHM_VERSION
from ..guest.service import fail, utcnow


# Approved Sandbox operator-test exception (see settlement/operator_cleanup.py).
CLEANUP_PURPOSE = "OPERATOR_TEST_CLEANUP"
CLEANUP_INTENT_KEY = "operator_test_cleanup"


def cleanup_intent(decision):
    return (decision.post_collection or {}).get(CLEANUP_INTENT_KEY) if decision is not None else None


def schema_available(db):
    return bool(db.scalar(text(
        "SELECT to_regclass('campaign_decisions') IS NOT NULL "
        "AND to_regclass('decision_cohort_members') IS NOT NULL "
        "AND to_regclass('settlement_work') IS NOT NULL"
    )))


def enqueue(db, campaign, *, purpose="PROGRESS", due_at=None):
    """Caller holds campaign lock; wakeups invalidate an old worker's completion."""
    work = db.scalar(select(SettlementWork).where(SettlementWork.campaign_id == campaign.id).with_for_update())
    due_at = due_at or utcnow()
    if work is None:
        work = SettlementWork(campaign_id=campaign.id, purpose=purpose, due_at=due_at)
        db.add(work)
    else:
        work.version += 1
        # A re-armed operator cleanup row stays scoped to that cleanup purpose;
        # wakeups never hand it back to the generic dispatcher.
        if work.purpose != CLEANUP_PURPOSE:
            work.purpose = purpose
        work.due_at = min(work.due_at, due_at) if work.state != "DONE" else due_at
        if work.state != "LEASED":
            work.state = "READY"
    return work


def freeze_decision(db, campaign_id, settings, *, now=None):
    """One campaign lock linearizes cutoff, admission closure and cohort identity."""
    campaign = db.scalar(select(Campaign).where(Campaign.id == campaign_id)
                         .with_for_update().execution_options(populate_existing=True))
    now = now or utcnow()
    if campaign is None:
        fail(404, "CAMPAIGN_NOT_FOUND", "Campaign not found.")
    existing = db.scalar(select(CampaignDecision).where(CampaignDecision.campaign_id == campaign_id))
    if existing is not None:
        db.commit()
        return existing
    if now < campaign.cutoff_at:
        fail(409, "CUTOFF_NOT_REACHED", "Deadline evaluation cannot run before cutoff.")
    if campaign.status != "OPEN":
        fail(409, "CAMPAIGN_NOT_OPEN", "Campaign is not available for a new deadline decision.")
    campaign.status = "DECIDING"
    terms = db.get(CampaignTerms, campaign.terms_id)
    bookings = list(db.scalars(select(Booking).where(Booking.campaign_id == campaign_id)
                              .order_by(Booking.id).with_for_update()
                              .execution_options(populate_existing=True)))
    deadline = campaign.settlement_deadline or campaign.cutoff_at + timedelta(seconds=settings.settlement_timeout_seconds)
    policy = {
        "collection_timeout_seconds": settings.settlement_timeout_seconds,
        "unknown_mutations": "retrieval-only; never replay a financial mutation",
        "fee_policy": "deduct max(frozen estimate, actual returned fee) per capture",
    }
    verified_ids = set(db.scalars(select(PaymentOperation.booking_id).where(
        PaymentOperation.booking_id.in_([b.id for b in bookings]),
        PaymentOperation.kind == "AUTHORIZE", PaymentOperation.state == "SUCCEEDED",
    )))
    eligible = [
        b for b in bookings
        if b.state == "AUTHORIZED" and b.admitted_at is not None and b.id in verified_ids
        and b.admitted_at <= campaign.cutoff_at and b.cancelled_at is None
        and b.provider_authorization_id and b.provider_order_id
        and b.terms_id == campaign.terms_id and b.currency == "GBP"
        and b.authorization_created_at is not None and b.authorization_expires_at is not None
        and min(b.authorization_expires_at, b.authorization_created_at + timedelta(hours=72)) > deadline
    ]
    result, reason, evidence = "RELEASE", "ACTUAL_ATTENDANCE_NOT_VIABLE", {}
    valid = False
    try:
        inputs = CampaignFinancialsInput.model_validate(terms.financial_inputs)
        valid = (
            terms.is_frozen and terms.version == campaign.terms_version
            and terms.algorithm_version == ALGORITHM_VERSION and inputs.fee_estimate is not None
            and terms.snapshot_hash == build_snapshot_hash(inputs, opens_at=terms.opens_at, closes_at=terms.closes_at)
            and inputs.capacity == campaign.capacity and terms.closes_at == campaign.cutoff_at
            and len(eligible) <= campaign.capacity
            and all(b.amount_minor == inputs.ticket_price_minor for b in eligible)
        )
        if valid:
            report = calculate_viability(inputs)
            evidence = {"algorithm_version": report.algorithm_version, "point": None}
            if len(eligible) >= report.minimum_operating_attendance and eligible:
                point = report.attendance_point(len(eligible))
                evidence["point"] = asdict(point)
                if point.is_viable:
                    result, reason = "COLLECT", "ACTUAL_ATTENDANCE_VIABLE"
    except (ValueError, KeyError, AttributeError):
        valid = False
    if not valid:
        result, reason = "REVIEW_REQUIRED", "FROZEN_TERMS_VALIDATION_FAILED"
    evidence["cohort_booking_ids"] = [str(b.id) for b in eligible]
    evidence["authorized_minor"] = sum(b.amount_minor for b in eligible)
    decision = CampaignDecision(
        campaign_id=campaign.id, terms_id=campaign.terms_id,
        terms_version=campaign.terms_version, snapshot_hash=terms.snapshot_hash,
        frozen_at=now, attendance=len(eligible), result=result, reason=reason,
        evidence=evidence, policy=policy, settlement_deadline=deadline,
        review_required=not valid,
    )
    db.add(decision)
    db.flush()
    for b in eligible:
        db.add(DecisionCohortMember(
            decision_id=decision.id, booking_id=b.id, order_id=b.provider_order_id,
            authorization_id=b.provider_authorization_id, amount_minor=b.amount_minor, currency=b.currency,
        ))
    campaign.settlement_deadline = deadline
    campaign.status = "SETTLING" if result == "COLLECT" and now < deadline else "RELEASING"
    enqueue(db, campaign)
    db.commit()
    return decision
