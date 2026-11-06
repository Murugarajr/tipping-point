"""Merchant workshop routes: draft, list, retrieve, edit, preview, publish.

Ownership is resolved server-side for every referenced workshop from
the authenticated session's merchant; a caller-supplied merchant ID is
never accepted (request schemas forbid it). Cross-merchant access
yields 404 so workshop existence is not leaked. Publishing is the
authoritative transaction defined in ``economics.publishing``.
"""

from __future__ import annotations

from datetime import datetime, timezone
import uuid as _uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.dependencies import (
    AuthContext,
    get_auth_context,
    get_db,
    require_csrf,
)
from ..channel3 import (
    Channel3AuthError,
    Channel3Client,
    Channel3Error,
    Channel3RateLimitError,
    Channel3ResponseError,
    Channel3TimeoutError,
    Channel3UnavailableError,
    Channel3UnconfiguredError,
)
from ..db.models import Campaign, CampaignTerms, MaterialOfferSnapshot, Workshop
from ..db.session import SessionLocal
from ..economics import (
    AlreadyPublishedError,
    CampaignFinancialsInput,
    CampaignTermsError,
    CampaignTermsService,
    InfeasibleCampaignError,
    MaterialLineInput,
    MaterialOfferProvenanceInput,
    WorkshopNotOwnedError,
    calculate_viability,
    publish_campaign,
)
from .schemas import (
    AttendancePointOut,
    CampaignOut,
    MaterialOfferSearchRequest,
    MaterialOfferSearchResponseOut,
    MaterialOfferSelectionOut,
    MaterialOfferSelectionRequest,
    MaterialOfferSnapshotOut,
    RejectedOfferCandidateOut,
    ViabilityPreviewOut,
    WorkshopCreateRequest,
    WorkshopEditRequest,
    WorkshopOut,
)

router = APIRouter(prefix="/api/merchant")


def _owned_workshop(
    db: Session,
    merchant_id,
    workshop_id: _uuid.UUID,
    *,
    for_update: bool = False,
) -> Workshop:
    stmt = select(Workshop).where(
        Workshop.id == workshop_id,
        Workshop.merchant_id == merchant_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    workshop = db.scalars(stmt).first()
    if workshop is None:
        raise HTTPException(status_code=404, detail="workshop not found")
    return workshop


def _latest_terms(db: Session, workshop_id) -> CampaignTerms:
    terms = db.scalars(
        select(CampaignTerms)
        .where(CampaignTerms.workshop_id == workshop_id)
        .order_by(CampaignTerms.version.desc())
        .limit(1)
    ).first()
    if terms is None:
        raise HTTPException(status_code=404, detail="workshop has no draft terms")
    return terms


def _open_campaign(db: Session, workshop_id) -> Campaign | None:
    return db.scalars(
        select(Campaign)
        .where(Campaign.workshop_id == workshop_id, Campaign.status == "OPEN")
        .limit(1)
    ).first()


def _workshop_out(db: Session, workshop: Workshop) -> WorkshopOut:
    terms = _latest_terms(db, workshop.id)
    return WorkshopOut(
        workshop_id=str(workshop.id),
        title=workshop.title,
        description=workshop.description,
        capacity=workshop.capacity,
        ticket_price_minor=workshop.ticket_price_minor,
        currency=workshop.currency,
        terms_version=terms.version,
        is_frozen=terms.is_frozen,
        opens_at=terms.opens_at,
        closes_at=terms.closes_at,
    )


@router.post("/workshops", status_code=201)
def create_workshop(
    payload: WorkshopCreateRequest,
    request: Request,
    auth: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> WorkshopOut:
    """Create a workshop with its first draft terms version."""
    require_csrf(request, auth)
    workshop = Workshop(
        merchant_id=auth.merchant.id,
        title=payload.title,
        description=payload.description,
        capacity=payload.financials.capacity,
        ticket_price_minor=payload.financials.ticket_price_minor,
        currency=payload.financials.currency,
    )
    db.add(workshop)
    db.flush()
    CampaignTermsService(db).create_draft(
        workshop.id, payload.financials, payload.schedule
    )
    return _workshop_out(db, workshop)


@router.get("/workshops")
def list_workshops(
    auth: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> list[WorkshopOut]:
    """List the merchant's own workshops only."""
    workshops = db.scalars(
        select(Workshop)
        .where(Workshop.merchant_id == auth.merchant.id)
        .order_by(Workshop.created_at.desc())
    ).all()
    return [_workshop_out(db, w) for w in workshops]


@router.get("/workshops/{workshop_id}")
def get_workshop(
    workshop_id: _uuid.UUID,
    auth: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> WorkshopOut:
    workshop = _owned_workshop(db, auth.merchant.id, workshop_id)
    return _workshop_out(db, workshop)


@router.patch("/workshops/{workshop_id}")
def edit_workshop(
    workshop_id: _uuid.UUID,
    payload: WorkshopEditRequest,
    request: Request,
    auth: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> WorkshopOut:
    """Edit a draft. Published terms cannot be edited (clear conflict)."""
    require_csrf(request, auth)
    # Row lock on the workshop serializes draft edits against concurrent
    # publish_campaign() calls for the same workshop.
    workshop = _owned_workshop(
        db, auth.merchant.id, workshop_id, for_update=True
    )
    terms = _latest_terms(db, workshop_id)
    db.refresh(terms)
    if _open_campaign(db, workshop_id) is not None or terms.is_frozen:
        raise HTTPException(
            status_code=409,
            detail="published terms are immutable; a material change "
            "requires the approved cancellation/new-campaign path",
        )
    if payload.title is not None:
        workshop.title = payload.title
    if payload.description is not None:
        workshop.description = payload.description
    workshop.capacity = payload.financials.capacity
    workshop.ticket_price_minor = payload.financials.ticket_price_minor
    workshop.currency = payload.financials.currency
    try:
        CampaignTermsService(db).update_draft(
            terms.id, payload.financials, payload.schedule
        )
    except CampaignTermsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return _workshop_out(db, workshop)


@router.post("/workshops/{workshop_id}/preview")
def preview_workshop(
    workshop_id: _uuid.UUID,
    request: Request,
    auth: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> ViabilityPreviewOut:
    """Preview economics from the CURRENT draft inputs.

    Pure calculation: nothing is persisted or mutated. Viability is
    exposed per attendance because reaching the first viable
    attendance does not imply every larger attendance is viable.
    """
    require_csrf(request, auth)
    _owned_workshop(db, auth.merchant.id, workshop_id)  # ownership enforced
    terms = _latest_terms(db, workshop_id)
    from ..economics import CampaignFinancialsInput

    inputs = CampaignFinancialsInput.model_validate(terms.financial_inputs)
    report = calculate_viability(inputs)
    materials_note = (
        "Channel3 offer snapshots are provider facts paired with merchant-reviewed "
        "pack, usage, suitability, and shipping assumptions; no stock, delivered-cost, "
        "quantity, or shipping-time guarantee is implied."
        if any(material.offer_provenance is not None for material in inputs.materials)
        else "Materials are merchant-entered assumptions, not Channel3 data; no Channel3 offer is selected."
    )
    return ViabilityPreviewOut(
        algorithm_version=report.algorithm_version,
        currency=report.currency,
        ticket_price_minor=report.ticket_price_minor,
        capacity=report.capacity,
        minimum_operating_attendance=report.minimum_operating_attendance,
        first_viable_attendance=report.first_viable_attendance,
        any_viable_attendance=report.any_viable_attendance,
        is_viable_at_capacity=report.is_viable_at_capacity,
        attendance_curve=[
            AttendancePointOut(
                attendance=p.attendance,
                packs_by_material=p.packs_by_material,
                material_cost_minor=p.material_cost_minor,
                required_budget_minor=p.required_budget_minor,
                gross_minor=p.gross_minor,
                estimated_fees_minor=p.estimated_fees_minor,
                estimated_net_minor=p.estimated_net_minor,
                estimated_surplus_minor=p.estimated_surplus_minor,
                is_viable=p.is_viable,
            )
            for p in report.attendance_curve
        ],
        materials_note=materials_note,
    )


@router.post("/workshops/{workshop_id}/publish")
def publish_workshop(
    workshop_id: _uuid.UUID,
    request: Request,
    response: Response,
    auth: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> CampaignOut:
    """Publish: freeze terms and open the campaign in one transaction.

    OPEN means published; it does not mean any guest has authorized
    payment or that the workshop is confirmed. Booking and payment
    capability is explicitly unavailable in this slice.
    """
    require_csrf(request, auth)
    try:
        campaign, created = publish_campaign(
            db,
            merchant=auth.merchant,
            workshop_id=workshop_id,
            stale_after_seconds=request.app.state.settings.channel3_offer_stale_after_seconds,
        )
    except WorkshopNotOwnedError:
        raise HTTPException(status_code=404, detail="workshop not found") from None
    except AlreadyPublishedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except InfeasibleCampaignError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except CampaignTermsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None

    # 201 when a new campaign was created; 200 for the idempotent
    # repeat publish of the same authoritative snapshot.
    response.status_code = 201 if created else 200
    terms = db.get(CampaignTerms, campaign.terms_id)
    assert terms is not None
    return CampaignOut(
        campaign_id=str(campaign.id),
        workshop_id=str(campaign.workshop_id),
        status=campaign.status,
        capacity=campaign.capacity,
        cutoff_at=campaign.cutoff_at,
        terms_version=campaign.terms_version,
        terms_id=str(campaign.terms_id),
        terms_snapshot_hash=terms.snapshot_hash,
    )