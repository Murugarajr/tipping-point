"""Authoritative campaign publishing.

Publishing is a single database transaction that: authorizes
ownership, takes a row lock on the workshop (serializing concurrent
publishes for that workshop), revalidates the draft terms through the
existing terms service, enforces the plan's rule that costs must be
coverable at MAXIMUM CAPACITY, freezes the exact terms snapshot, and
creates the campaign with an authoritative reference to that frozen
snapshot. OPEN means published — it does NOT mean any guest has
authorized payment or that the workshop is confirmed; booking and
payment capability is explicitly unavailable in this slice.

Repeated publishes are idempotent when they reference the same terms;
a publish after materially different terms exist is a clear conflict.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Campaign, Merchant, Workshop
from .errors import AlreadyPublishedError, InfeasibleCampaignError
from .schemas import CampaignFinancialsInput
from .service import CampaignTermsService


class WorkshopNotOwnedError(LookupError):
    """The workshop does not exist for this merchant (404, no existence leak)."""


def _latest_terms(session: Session, workshop_id):
    from ..db.models import CampaignTerms

    return session.scalars(
        select(CampaignTerms)
        .where(CampaignTerms.workshop_id == workshop_id)
        .order_by(CampaignTerms.version.desc())
        .limit(1)
    ).first()


def _open_campaign(session: Session, workshop_id):
    return session.scalars(
        select(Campaign)
        .where(Campaign.workshop_id == workshop_id, Campaign.status == "OPEN")
        .limit(1)
    ).first()


def publish_campaign(
    session: Session,
    *,
    merchant: Merchant,
    workshop_id,
    stale_after_seconds: int | None = None,
) -> tuple[Campaign, bool]:
    """Freeze the current draft terms and publish the campaign.

    Returns (campaign, created). ``created`` is False for an idempotent
    repeat publish of the same terms snapshot. Runs inside the
    caller's transaction. Raises WorkshopNotOwnedError,
    AlreadyPublishedError, InfeasibleCampaignError, or the terms
    service's validation errors; the caller rolls back, so a failed
    publish leaves no frozen terms and no campaign.
    """
    # Row lock on the workshop serializes concurrent publishes for the
    # same workshop and anchors the ownership check.
    workshop = session.scalars(
        select(Workshop)
        .where(
            Workshop.id == workshop_id,
            Workshop.merchant_id == merchant.id,
        )
        .with_for_update()
    ).first()
    if workshop is None:
        raise WorkshopNotOwnedError(
            f"workshop {workshop_id} does not exist for this merchant"
        )

    existing = _open_campaign(session, workshop_id)
    terms = _latest_terms(session, workshop_id)
    if terms is None:
        raise WorkshopNotOwnedError("workshop has no draft terms")
    session.refresh(terms)  # ensure locked/current read under the row lock

    if existing is not None:
        if existing.terms_id == terms.id:
            # Idempotent repeat publish: same authoritative snapshot.
            return existing, False
        raise AlreadyPublishedError(
            "a published campaign already exists for this workshop; "
            "materially different terms require the approved "
            "cancellation/new-campaign path"
        )

    if terms.is_frozen:
        # Frozen without a campaign should not occur; refuse rather
        # than silently recalculating live terms.
        raise AlreadyPublishedError("terms are already frozen")

    # Revalidation happens inside freeze(): positive ticket price,
    # explicit fee estimate, valid and future campaign dates within the
    # approved maximum duration, and a reproducible snapshot hash.
    CampaignTermsService(session).freeze(
        terms.id, stale_after_seconds=stale_after_seconds
    )

    # Plan rule: block publishing when costs cannot be covered at
    # maximum capacity. Reaching the first viable attendance does not
    # imply every larger attendance is viable, so the gate is capacity.
    if not terms.calculation["is_viable_at_capacity"]:
        raise InfeasibleCampaignError(
            "costs cannot be covered at maximum capacity; publishing is blocked"
        )

    inputs = CampaignFinancialsInput.model_validate(terms.financial_inputs)
    campaign = Campaign(
        workshop_id=workshop_id,
        terms_id=terms.id,
        status="OPEN",
        capacity=inputs.capacity,
        cutoff_at=terms.closes_at,
        terms_version=terms.version,
    )
    session.add(campaign)
    session.flush()
    return campaign, True