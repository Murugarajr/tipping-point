"""Role-safe read-only projections; never dispatch financial work from a GET."""

from sqlalchemy import select

from ..db.models import Booking, CampaignDecision, DecisionCohortMember, PaymentOperation
from .decision import schema_available


def _cleanup(campaign, decision, members, bookings, operations):
    from .operator_cleanup import cleanup_presentation
    if decision is None or len(members) != 1:
        return None
    member = members[0]
    booking = next((b for b in bookings if b.id == member.booking_id), None)
    refund = next((o for o in operations if o.booking_id == member.booking_id and o.kind == "REFUND"), None)
    return cleanup_presentation(campaign, decision, member, booking, refund)


def campaign_projection(db, campaign):
    if not schema_available(db):
        return None
    decision = db.scalar(select(CampaignDecision).where(CampaignDecision.campaign_id == campaign.id))
    bookings = list(db.scalars(select(Booking).where(Booking.campaign_id == campaign.id)))
    members = list(db.scalars(select(DecisionCohortMember).where(
        DecisionCohortMember.decision_id == decision.id))) if decision else []
    point = (decision.evidence.get("point") or {}) if decision else {}
    post = decision.post_collection if decision else {}
    operations = list(db.scalars(select(PaymentOperation).where(PaymentOperation.booking_id.in_([b.id for b in bookings]))))
    pending_captures = {o.booking_id for o in operations if o.kind == "CAPTURE" and o.state in ("IN_FLIGHT", "UNKNOWN", "PROVIDER_PENDING")}
    pending_releases = {o.booking_id for o in operations if o.kind == "VOID" and o.state != "SUCCEEDED"}
    collected = sum(m.amount_minor for m in members if m.capture_status == "COMPLETED")
    refunded = sum(m.amount_minor for m in members if m.refund_status == "COMPLETED")
    return {
        "state": campaign.status, "decision_result": decision.result if decision else None,
        "decision_reason": decision.reason if decision else None,
        "frozen_attendance": decision.attendance if decision else None,
        "admitted_attendance": sum(b.admitted_at is not None and b.cancelled_at is None and b.state not in ("VOIDED", "REFUNDED") for b in bookings),
        "authorized_minor": sum(b.amount_minor for b in bookings if b.admitted_at and b.state not in ("VOIDED", "REFUNDED", "PAID", "REFUND_PENDING") and b.id not in {m.booking_id for m in members if m.capture_status == "COMPLETED"}),
        "collected_minor": collected,
        "refunded_minor": refunded,
        "net_collected_minor": collected - refunded,
        "capture_pending": len(pending_captures),
        "release_pending": len(pending_releases),
        "refund_pending": sum(b.state == "REFUND_PENDING" for b in bookings),
        "review_required": bool(decision and decision.review_required) or any(b.state == "REVIEW_REQUIRED" for b in bookings),
        "settlement_deadline": decision.settlement_deadline if decision else campaign.settlement_deadline,
        "fee_basis": post.get("fee_basis", "estimated"),
        "actual_fees_minor": post.get("actual_fees_minor"),
        "estimated_fees_minor": point.get("estimated_fees_minor"),
        "estimated_surplus_minor": point.get("estimated_surplus_minor"),
        "post_collection_surplus_minor": post.get("surplus_minor"),
        "sandbox_cleanup": _cleanup(campaign, decision, members, bookings, operations),
    }


def guest_projection(db, booking, campaign):
    result = {"campaign_status": campaign.status, "workshop_confirmed": False,
              "captured_minor": 0, "refunded_minor": 0, "sandbox_cleanup_status": None}
    if not schema_available(db):
        return result
    member = db.scalar(select(DecisionCohortMember).where(DecisionCohortMember.booking_id == booking.id))
    if member:
        result["captured_minor"] = member.amount_minor if member.capture_status == "COMPLETED" else 0
        result["refunded_minor"] = member.amount_minor if member.refund_status == "COMPLETED" else 0
        result["workshop_confirmed"] = campaign.status == "CONFIRMED" and booking.state == "PAID" and member.capture_status == "COMPLETED" and not member.refund_id
        decision = db.get(CampaignDecision, member.decision_id)
        refund = db.scalar(select(PaymentOperation).where(
            PaymentOperation.booking_id == booking.id, PaymentOperation.kind == "REFUND"))
        from .operator_cleanup import cleanup_presentation
        cleanup = cleanup_presentation(campaign, decision, member, booking, refund)
        result["sandbox_cleanup_status"] = cleanup["status"] if cleanup else None
    return result
