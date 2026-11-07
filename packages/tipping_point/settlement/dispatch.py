"""Database-backed bounded work claims. No browser, sleep loop, or remote SDK."""

from dataclasses import dataclass
from datetime import timedelta
import uuid

from sqlalchemy import or_, select

from ..db.models import Campaign, SettlementWork
from ..guest.service import utcnow
from .decision import enqueue, freeze_decision


@dataclass(frozen=True)
class WorkClaim:
    id: uuid.UUID
    campaign_id: uuid.UUID
    token: uuid.UUID
    version: int


def discover_due(db, *, limit=100, now=None, campaign_id=None):
    """Backfill old published campaigns; bounded and serialized by campaign locks."""
    now = now or utcnow()
    query = select(Campaign).where(Campaign.status == "OPEN", Campaign.cutoff_at <= now)
    if campaign_id is not None:
        query = query.where(Campaign.id == campaign_id)
    rows = list(db.scalars(query.order_by(Campaign.cutoff_at).limit(limit).with_for_update(skip_locked=True)))
    for campaign in rows:
        if not db.scalar(select(SettlementWork.id).where(SettlementWork.campaign_id == campaign.id)):
            enqueue(db, campaign, purpose="DEADLINE", due_at=campaign.cutoff_at)
    db.commit()
    return len(rows)


def claim_due(db, *, now=None, campaign_id=None):
    now = now or utcnow()
    query = select(SettlementWork).where(
        SettlementWork.due_at <= now,
        or_(SettlementWork.state == "READY",
            (SettlementWork.state == "LEASED") & (SettlementWork.lease_expires_at <= now)),
    )
    if campaign_id is not None:
        query = query.where(SettlementWork.campaign_id == campaign_id)
    work = db.scalar(query.order_by(SettlementWork.due_at).limit(1).with_for_update(skip_locked=True))
    if work is None:
        db.commit()
        return None
    work.state, work.claim_token = "LEASED", uuid.uuid4()
    work.version += 1
    work.attempts += 1
    work.lease_expires_at = now + timedelta(minutes=2)
    claim = WorkClaim(work.id, work.campaign_id, work.claim_token, work.version)
    db.commit()
    return claim


def finish_work(db, claim, *, terminal=False, error=None):
    work = db.scalar(select(SettlementWork).where(SettlementWork.id == claim.id).with_for_update()
                     .execution_options(populate_existing=True))
    if work.claim_token != claim.token:
        db.commit()
        return False
    unchanged = work.version == claim.version
    work.state = "DONE" if terminal and unchanged else "READY"
    work.lease_expires_at = None
    work.claim_token = None
    if unchanged:
        work.due_at = utcnow() + timedelta(seconds=60)
    work.last_error = error
    db.commit()
    return unchanged


async def process_due(db, settings, gateway, *, limit=10, campaign_id=None):
    """Invoke from a local operator or a thin external workflow adapter."""
    from .service import SettlementService
    discover_due(db, limit=limit, campaign_id=campaign_id)
    results = []
    for _ in range(limit):
        claim = claim_due(db, campaign_id=campaign_id)
        if claim is None:
            break
        try:
            freeze_decision(db, claim.campaign_id, settings)
            if gateway is not None:
                await SettlementService(db, settings, gateway).advance(claim.campaign_id)
            campaign = db.get(Campaign, claim.campaign_id, populate_existing=True)
            terminal = campaign.status in ("CONFIRMED", "CANCELLED")
            if terminal:
                from ..db.models import Booking, PaymentOperation
                pending = db.scalar(select(PaymentOperation.id).join(Booking).where(
                    Booking.campaign_id == campaign.id,
                    PaymentOperation.state.in_(("IN_FLIGHT", "UNKNOWN", "PROVIDER_PENDING")),
                ).limit(1))
                terminal = pending is None
            results.append({"campaign_id": str(campaign.id), "state": campaign.status})
            db.commit()
            finish_work(db, claim, terminal=terminal)
        except Exception as error:
            db.rollback()
            finish_work(db, claim, error=type(error).__name__)
            results.append({"campaign_id": str(claim.campaign_id), "error": type(error).__name__})
    return results
