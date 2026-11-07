"""Short transaction guest reservations, independent of provider network I/O."""

from datetime import datetime, timedelta, timezone
import hashlib
import json
import uuid

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select, text

from ..db.models import Booking, BookingEvent, Campaign, CampaignTerms, GuestSession, Workshop
from ..economics import CampaignFinancialsInput, build_snapshot_hash
from .schemas import BookingOut

HOLD_STATES = ("CHECKOUT_RESERVED", "AWAITING_APPROVAL", "AUTHORIZATION_PENDING", "REVIEW_REQUIRED")
NOTICE = "This Sandbox prototype authorizes a test payment. An authorization is not a completed charge. The workshop is not confirmed by this step."


def utcnow():
    return datetime.now(timezone.utc)


def fail(status, code, message):
    raise HTTPException(status_code=status, detail={"code": code, "message": message})


def payload_hash(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def guest_schema_available(db):
    # Catalog lookup is non-failing even while the development DB remains 0004.
    return bool(db.scalar(text(
        "SELECT to_regclass('guest_sessions') IS NOT NULL "
        "AND to_regclass('bookings') IS NOT NULL "
        "AND to_regclass('payment_operations') IS NOT NULL "
        "AND to_regclass('booking_events') IS NOT NULL"
    )))


def capacity_predicate(now):
    return or_(
        and_(Booking.admitted_at.is_not(None), Booking.state.notin_(("VOIDED", "REFUNDED"))),
        and_(Booking.state.in_(HOLD_STATES), Booking.cancelled_at.is_(None),
             Booking.reservation_expires_at > now),
    )


def capacity_count(db, campaign_id, now, exclude_booking_id=None):
    query = select(func.count()).select_from(Booking).where(
        Booking.campaign_id == campaign_id, capacity_predicate(now)
    )
    if exclude_booking_id is not None:
        query = query.where(Booking.id != exclude_booking_id)
    return db.scalar(query) or 0


def availability(db, campaign, terms, settings, *, now=None, schema_available=None):
    now = now or utcnow()
    if (
        campaign.status != "OPEN" or not terms.is_frozen or terms.currency != "GBP"
        or terms.opens_at is None or terms.closes_at is None
    ):
        return False, "ineligible", None
    if now >= min(campaign.cutoff_at, terms.closes_at):
        return False, "closed", None
    if now < terms.opens_at:
        return False, "not_open_yet", None
    if not settings.reservations_configured:
        return False, "payment_unconfigured", None
    if schema_available is None:
        schema_available = guest_schema_available(db)
    if not schema_available:
        return False, "schema_unavailable", None
    seats = max(0, campaign.capacity - capacity_count(db, campaign.id, now))
    return seats > 0, "available" if seats else "full", seats


class BookingService:
    def __init__(self, db, settings):
        self.db = db
        self.settings = settings

    def owned(self, guest_id, booking_id):
        booking = self.db.scalar(select(Booking).where(
            Booking.id == booking_id, Booking.guest_session_id == guest_id
        ))
        if booking is None:
            fail(404, "BOOKING_NOT_FOUND", "Reservation not found for this guest session.")
        return booking

    def reserve(self, guest_id, campaign_id, email, idempotency_key, *, now=None):
        supplied_now = now
        now = now or utcnow()
        email = email.strip().lower()
        request_hash = payload_hash({"campaign_id": str(campaign_id), "email": email})
        # Consistent guest -> campaign lock order serializes retries and lost-key
        # duplicate submissions before counting capacity.
        guest = self.db.scalar(select(GuestSession).where(GuestSession.id == guest_id).with_for_update())
        if guest is None or guest.revoked_at or guest.expires_at <= now:
            fail(401, "GUEST_SESSION_REQUIRED", "An active guest session is required.")
        existing = self.db.scalar(select(Booking).where(
            Booking.guest_session_id == guest_id, Booking.idempotency_key == idempotency_key
        ))
        if existing:
            if existing.reservation_payload_hash != request_hash:
                fail(409, "IDEMPOTENCY_CONFLICT", "This request key was used with different reservation details.")
            return existing
        campaign = self.db.scalar(select(Campaign).where(Campaign.id == campaign_id).with_for_update())
        if campaign is None:
            fail(404, "CAMPAIGN_NOT_FOUND", "Published campaign not found.")
        now = supplied_now or utcnow()
        if guest.expires_at <= now:
            fail(401, "GUEST_SESSION_REQUIRED", "Your guest session expired during reservation.")
        active = self.db.scalar(select(Booking).where(
            Booking.guest_session_id == guest_id, Booking.campaign_id == campaign_id,
            capacity_predicate(now),
        ))
        if active:
            if active.email != email:
                fail(409, "IDEMPOTENCY_CONFLICT", "An active reservation already exists with different contact details.")
            return active
        terms = self.db.get(CampaignTerms, campaign.terms_id)
        if terms is None or terms.workshop_id != campaign.workshop_id or terms.version != campaign.terms_version:
            fail(503, "RESERVATIONS_UNAVAILABLE", "Published terms are unavailable.")
        enabled, reason, _ = availability(self.db, campaign, terms, self.settings, now=now)
        if not enabled:
            statuses = {
                "not_open_yet": (409, "BOOKING_NOT_OPEN"),
                "closed": (409, "BOOKING_CLOSED"), "full": (409, "CAPACITY_EXHAUSTED"),
                "ineligible": (409, "BOOKING_CLOSED"),
                "payment_unconfigured": (503, "PAYMENT_UNAVAILABLE"),
                "schema_unavailable": (503, "RESERVATIONS_UNAVAILABLE"),
            }
            status, code = statuses[reason]
            fail(status, code, "Reservations are unavailable: " + reason.replace("_", " ") + ".")
        inputs = CampaignFinancialsInput.model_validate(terms.financial_inputs)
        if (
            inputs.capacity != campaign.capacity or inputs.ticket_price_minor <= 0 or inputs.fee_estimate is None
            or build_snapshot_hash(inputs, opens_at=terms.opens_at, closes_at=terms.closes_at) != terms.snapshot_hash
        ):
            fail(503, "RESERVATIONS_UNAVAILABLE", "Published terms are inconsistent.")
        booking_id = uuid.uuid4()
        root = f"{self.settings.public_url}/bookings/{booking_id}/paypal"
        booking = Booking(
            id=booking_id, guest_session_id=guest_id, campaign_id=campaign_id,
            terms_id=terms.id, idempotency_key=idempotency_key,
            reservation_payload_hash=request_hash, email=email,
            amount_minor=inputs.ticket_price_minor, currency=inputs.currency,
            expected_payee=self.settings.paypal_expected_payee.strip(),
            return_url=root + "/return", cancel_url=root + "/cancel",
            state="CHECKOUT_RESERVED",
            reservation_expires_at=min(now + timedelta(minutes=10), campaign.cutoff_at, terms.closes_at),
        )
        self.db.add(booking)
        self.db.flush()
        self.db.add(BookingEvent(booking_id=booking.id, kind="RESERVED", details={"terms_id": str(terms.id)}))
        return booking

    def booking_out(self, booking, *, now=None):
        now = now or utcnow()
        campaign = self.db.get(Campaign, booking.campaign_id)
        workshop = self.db.get(Workshop, campaign.workshop_id)
        state = booking.state
        if state in ("CHECKOUT_RESERVED", "AWAITING_APPROVAL") and booking.reservation_expires_at <= now:
            state = "EXPIRED"
        live = (
            booking.cancelled_at is None and booking.reservation_expires_at > now
            and campaign.status == "OPEN" and now < campaign.cutoff_at
        )
        payment = {
            "CHECKOUT_RESERVED": "NOT_STARTED", "AWAITING_APPROVAL": "AWAITING_APPROVAL",
            "AUTHORIZATION_PENDING": "CHECKING", "AUTHORIZED": "AUTHORIZED",
            "RELEASE_PENDING": "RELEASE_PENDING", "VOIDED": "VOIDED",
            "REVIEW_REQUIRED": "REVIEW_REQUIRED",
            "CAPTURE_PENDING": "CAPTURE_PENDING", "PAID": "PAID",
            "REFUND_PENDING": "REFUND_PENDING", "REFUNDED": "REFUNDED",
        }.get(state, "NOT_STARTED")
        from ..settlement.projections import guest_projection
        settlement = guest_projection(self.db, booking, campaign)
        return BookingOut(
            booking_id=booking.id, campaign_id=campaign.id, workshop_id=workshop.id,
            workshop_title=workshop.title, state=state, payment_state=payment,
            amount_minor=booking.amount_minor, currency=booking.currency,
            reservation_expires_at=booking.reservation_expires_at,
            seat_held=(booking.admitted_at is not None and state not in ("VOIDED", "REFUNDED")) or (live and state in HOLD_STATES),
            approve_url=booking.approve_url if live and state == "AWAITING_APPROVAL" else None,
            notice={
                "CAPTURE_PENDING": "Sandbox collection is pending or being checked; no completed collection or workshop confirmation is assumed.",
                "PAID": "Sandbox payment collection was verified. Workshop confirmation depends on the saved campaign settlement state.",
                "REFUND_PENDING": "Sandbox refund processing or reconciliation is pending. No instant refund or completed cleanup is promised.",
                "REFUNDED": "The full Sandbox refund was verified. This reservation is not a confirmed workshop place.",
            }.get(state, NOTICE), can_create_order=live and state == "CHECKOUT_RESERVED",
            can_authorize=live and state == "AWAITING_APPROVAL",
            can_cancel=state not in ("VOIDED", "CANCELLED", "EXPIRED", "REFUNDED", "REFUND_PENDING") and booking.cancelled_at is None and campaign.status != "CONFIRMED",
            updated_at=booking.updated_at,
            **settlement,
        )
