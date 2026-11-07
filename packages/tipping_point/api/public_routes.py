"""Read-only discovery projected from authoritative published frozen terms."""

from datetime import datetime, timezone
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth.dependencies import get_db
from ..db.models import Campaign, CampaignTerms, Workshop
from ..economics import CampaignFinancialsInput
from ..guest.service import availability
from .schemas import PublicWorkshopOut

router = APIRouter(prefix="/api/workshops")


def _published_query():
    ranked = select(
        Campaign.id.label("campaign_id"),
        func.row_number().over(
            partition_by=Campaign.workshop_id,
            order_by=(Campaign.created_at.desc(), Campaign.id.desc()),
        ).label("position"),
    ).where(Campaign.status != "DRAFT").subquery()
    return (
        select(Workshop, Campaign, CampaignTerms)
        .join(Campaign, Campaign.workshop_id == Workshop.id)
        .join(ranked, ranked.c.campaign_id == Campaign.id)
        .join(CampaignTerms, CampaignTerms.id == Campaign.terms_id)
        .where(
            ranked.c.position == 1,
            CampaignTerms.is_frozen.is_(True),
            CampaignTerms.workshop_id == Workshop.id,
            CampaignTerms.version == Campaign.terms_version,
            CampaignTerms.opens_at.is_not(None),
            CampaignTerms.closes_at.is_not(None),
        )
    )


def _public_workshop(workshop, campaign, terms, *, now=None, db=None, settings=None) -> PublicWorkshopOut:
    inputs = CampaignFinancialsInput.model_validate(terms.financial_inputs)
    now = now or datetime.now(timezone.utc)
    if campaign.status != "OPEN":
        window = "unavailable"
    elif now >= terms.closes_at:
        window = "closed"
    elif now < terms.opens_at:
        window = "not_open_yet"
    else:
        window = "open"
    availability_fields = {}
    if db is not None and settings is not None:
        enabled, reason, seats = availability(db, campaign, terms, settings, now=now)
        availability_fields = dict(
            reservations_available=enabled, availability_reason=reason, available_seats=seats,
            availability_note=(
                "Reserve one place with a PayPal Sandbox test authorization; this is not a completed charge."
                if enabled else "Reservations unavailable: " + reason.replace("_", " ") + "."
            ),
        )
    return PublicWorkshopOut(
        workshop_id=str(workshop.id), campaign_id=str(campaign.id),
        # Merchant APIs reject copy edits once the terms are frozen.
        title=workshop.title, description=workshop.description,
        currency=inputs.currency, ticket_price_minor=inputs.ticket_price_minor,
        capacity=inputs.capacity, opens_at=terms.opens_at, cutoff_at=terms.closes_at,
        publication_status=campaign.status, booking_window_status=window,
        **availability_fields,
    )


@router.get("", response_model=list[PublicWorkshopOut])
def list_public_workshops(request: Request, response: Response, db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    rows = db.execute(_published_query().order_by(Campaign.created_at.desc()).limit(100)).all()
    return [_public_workshop(*row, db=db, settings=request.app.state.settings) for row in rows]


@router.get("/{workshop_id}", response_model=PublicWorkshopOut)
def get_public_workshop(
    workshop_id: uuid.UUID, request: Request, response: Response, db: Session = Depends(get_db)
):
    response.headers["Cache-Control"] = "no-store"
    row = db.execute(_published_query().where(Workshop.id == workshop_id)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="published workshop not found")
    return _public_workshop(*row, db=db, settings=request.app.state.settings)
