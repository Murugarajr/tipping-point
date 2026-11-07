"""Authenticated material offer discovery and selection routes.

Channel3 network I/O is performed only after committing the ownership/draft
check transaction, never while holding the workshop row lock. Provider facts
are persisted as immutable snapshots; merchant assumptions are submitted
separately when selecting an offer.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.dependencies import AuthContext, get_auth_context, get_db, require_csrf
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
from ..economics import (
    CampaignFinancialsInput,
    CampaignTermsService,
    MaterialLineInput,
    MaterialOfferProvenanceInput,
    calculate_viability,
)
from .schemas import (
    AttendancePointOut,
    MaterialOfferSearchRequest,
    MaterialOfferSearchResponseOut,
    MaterialOfferSelectionOut,
    MaterialOfferSelectionRequest,
    MaterialOfferSnapshotOut,
    RejectedOfferCandidateOut,
    ViabilityPreviewOut,
    WorkshopOut,
)

router = APIRouter(prefix="/api/merchant")


def _owned_draft(session: Session, merchant_id, workshop_id: uuid.UUID, *, lock: bool):
    statement = select(Workshop).where(
        Workshop.id == workshop_id,
        Workshop.merchant_id == merchant_id,
    )
    if lock:
        statement = statement.with_for_update()
    workshop = session.scalars(statement).first()
    if workshop is None:
        raise HTTPException(status_code=404, detail="workshop not found")
    terms = session.scalars(
        select(CampaignTerms)
        .where(CampaignTerms.workshop_id == workshop_id)
        .order_by(CampaignTerms.version.desc())
        .limit(1)
    ).first()
    if terms is None:
        raise HTTPException(status_code=404, detail="workshop has no draft terms")
    session.refresh(terms)
    campaign = session.scalars(
        select(Campaign).where(
            Campaign.workshop_id == workshop_id,
            Campaign.status == "OPEN",
        ).limit(1)
    ).first()
    if terms.is_frozen or campaign is not None:
        raise HTTPException(
            status_code=409,
            detail="published terms are immutable; a material change requires the approved cancellation/new-campaign path",
        )
    return workshop, terms


def _channel3(request: Request) -> Channel3Client:
    override = getattr(request.app.state, "channel3_client", None)
    if override is not None:
        return override
    settings = request.app.state.settings
    key = (
        settings.channel3_api_key.get_secret_value()
        if settings.channel3_api_key is not None
        else None
    )
    return Channel3Client(
        api_key=key,
        base_url=settings.channel3_base_url,
        timeout_seconds=settings.channel3_timeout_seconds,
    )


def _stale_after(request: Request) -> int:
    return request.app.state.settings.channel3_offer_stale_after_seconds


def _offer_out(snapshot: MaterialOfferSnapshot, *, stale_after: int) -> MaterialOfferSnapshotOut:
    age_seconds = max(
        0.0,
        (datetime.now(timezone.utc) - snapshot.retrieved_at).total_seconds(),
    )
    stale = age_seconds > stale_after
    return MaterialOfferSnapshotOut(
        offer_snapshot_id=str(snapshot.id),
        workshop_id=str(snapshot.workshop_id),
        provider=snapshot.provider,
        search_query=snapshot.search_query,
        provider_product_id=snapshot.provider_product_id,
        provider_offer_ref=snapshot.provider_offer_ref,
        product_title=snapshot.product_title,
        brand_name=snapshot.brand_name,
        merchant_domain=snapshot.merchant_domain,
        reported_price_raw=snapshot.reported_price_raw,
        price_minor=snapshot.price_minor,
        currency=snapshot.currency,
        product_url=snapshot.product_url,
        image_url=snapshot.image_url,
        availability=snapshot.availability,
        condition=snapshot.condition,
        locale_country=snapshot.locale_country,
        locale_language=snapshot.locale_language,
        locale_currency=snapshot.locale_currency,
        retrieved_at=snapshot.retrieved_at,
        is_stale=stale,
        freshness_label="stale; original cached price" if stale else "fresh at retrieval",
    )


def _preview(inputs: CampaignFinancialsInput, terms: CampaignTerms) -> ViabilityPreviewOut:
    report = calculate_viability(inputs)
    note = (
        "Channel3 offer snapshots are provider facts paired with merchant-reviewed pack, usage, suitability, and shipping assumptions; no stock, delivered-cost, quantity, or shipping-time guarantee is implied."
        if any(material.offer_provenance is not None for material in inputs.materials)
        else "Materials are merchant-entered assumptions; no Channel3 offer is selected."
    )
    return ViabilityPreviewOut(
        algorithm_version=report.algorithm_version,
        terms_version=terms.version,
        terms_snapshot_hash=terms.snapshot_hash,
        currency=report.currency,
        ticket_price_minor=report.ticket_price_minor,
        capacity=report.capacity,
        minimum_operating_attendance=report.minimum_operating_attendance,
        first_viable_attendance=report.first_viable_attendance,
        any_viable_attendance=report.any_viable_attendance,
        is_viable_at_capacity=report.is_viable_at_capacity,
        attendance_curve=[
            AttendancePointOut(
                attendance=point.attendance,
                packs_by_material=point.packs_by_material,
                material_cost_minor=point.material_cost_minor,
                required_budget_minor=point.required_budget_minor,
                gross_minor=point.gross_minor,
                estimated_fees_minor=point.estimated_fees_minor,
                estimated_net_minor=point.estimated_net_minor,
                estimated_surplus_minor=point.estimated_surplus_minor,
                is_viable=point.is_viable,
            )
            for point in report.attendance_curve
        ],
        materials_note=note,
    )

    return request.app.state.settings.channel3_offer_stale_after_seconds


@router.post(
    "/workshops/{workshop_id}/materials/search",
    response_model=MaterialOfferSearchResponseOut,
)
def search_material_offers(
    workshop_id: uuid.UUID,
    payload: MaterialOfferSearchRequest,
    request: Request,
    auth: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> MaterialOfferSearchResponseOut:
    """Search provider outside transactions, then persist provenance snapshots."""
    require_csrf(request, auth)
    client = _channel3(request)
    if not client.is_configured:
        raise HTTPException(
            status_code=503,
            detail={"state": "unconfigured", "message": "Channel3 material search is not configured"},
        )

    # The ownership/draft row lock is released before the external call.
    _owned_draft(db, auth.merchant.id, workshop_id, lock=True)
    db.commit()
    try:
        result = client.search_offers(
            payload.query,
            limit=payload.limit,
            in_stock_only=payload.in_stock_only,
            max_attempts=2,
        )
    except Channel3UnconfiguredError:
        raise HTTPException(
            status_code=503,
            detail={"state": "unconfigured", "message": "Channel3 material search is not configured"},
        ) from None
    except Channel3RateLimitError as exc:
        headers = {}
        if exc.retry_after_seconds is not None:
            headers["Retry-After"] = str(exc.retry_after_seconds)
        raise HTTPException(
            status_code=429,
            detail={"state": "rate_limited", "message": str(exc)},
            headers=headers,
        ) from None
    except Channel3TimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail={"state": "unavailable", "message": str(exc)},
        ) from None
    except Channel3AuthError as exc:
        raise HTTPException(
            status_code=503,
            detail={"state": "unavailable", "message": str(exc)},
        ) from None
    except (Channel3UnavailableError, Channel3ResponseError) as exc:
        raise HTTPException(
            status_code=503,
            detail={"state": "unavailable", "message": str(exc)},
        ) from None
    except Channel3Error:
        raise HTTPException(
            status_code=503,
            detail={"state": "unavailable", "message": "Channel3 material search is unavailable"},
        ) from None

    # Recheck draft state after I/O; do not persist results if publish raced.
    _owned_draft(db, auth.merchant.id, workshop_id, lock=True)
    persisted: list[MaterialOfferSnapshotOut] = []
    rejected: list[RejectedOfferCandidateOut] = []
    for candidate in result.offers:
        if not candidate.costing_eligible:
            rejected.append(
                RejectedOfferCandidateOut(
                    provider_product_id=candidate.provider_product_id,
                    provider_offer_ref=candidate.provider_offer_ref,
                    product_title=candidate.product_title,
                    merchant_domain=candidate.merchant_domain,
                    reported_price_raw=candidate.reported_price_raw,
                    currency=candidate.currency,
                    ineligible_reason=candidate.ineligible_reason or "not eligible for costing",
                )
            )
            continue
        snapshot = MaterialOfferSnapshot(
            merchant_id=auth.merchant.id,
            workshop_id=workshop_id,
            provider="channel3",
            search_query=result.query,
            provider_product_id=candidate.provider_product_id,
            provider_offer_ref=candidate.provider_offer_ref,
            product_title=candidate.product_title,
            brand_name=candidate.brand_name,
            merchant_domain=candidate.merchant_domain,
            reported_price_raw=candidate.reported_price_raw or "",
            price_minor=candidate.price_minor,
            currency=candidate.currency,
            product_url=candidate.product_url,
            image_url=candidate.image_url,
            availability=candidate.availability,
            condition=candidate.condition,
            locale_country=candidate.locale_country,
            locale_language=candidate.locale_language,
            locale_currency=candidate.locale_currency,
            retrieved_at=candidate.retrieved_at,
        )
        db.add(snapshot)
        db.flush()
        persisted.append(_offer_out(snapshot, stale_after=_stale_after(request)))
    db.commit()
    return MaterialOfferSearchResponseOut(
        workshop_id=str(workshop_id),
        query=result.query,
        locale_country=result.locale_country,
        locale_language=result.locale_language,
        locale_currency=result.locale_currency,
        retrieved_at=result.retrieved_at,
        offers=persisted,
        rejected_offers=rejected,
        eligible_count=len(persisted),
        rejected_count=len(rejected),
    )


@router.post(
    "/workshops/{workshop_id}/materials/select",
    response_model=MaterialOfferSelectionOut,
)
def select_material_offer(
    workshop_id: uuid.UUID,
    payload: MaterialOfferSelectionRequest,
    request: Request,
    auth: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> MaterialOfferSelectionOut:
    """Select a private server offer and record reviewed assumptions."""
    require_csrf(request, auth)
    try:
        offer_id = uuid.UUID(payload.offer_snapshot_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="material offer not found") from None

    workshop, terms = _owned_draft(db, auth.merchant.id, workshop_id, lock=True)
    snapshot = db.scalars(
        select(MaterialOfferSnapshot).where(
            MaterialOfferSnapshot.id == offer_id,
            MaterialOfferSnapshot.merchant_id == auth.merchant.id,
            MaterialOfferSnapshot.workshop_id == workshop_id,
        )
    ).first()
    if snapshot is None:
        raise HTTPException(status_code=404, detail="material offer not found")
    age = (datetime.now(timezone.utc) - snapshot.retrieved_at).total_seconds()
    if age > _stale_after(request):
        raise HTTPException(
            status_code=409,
            detail="offer snapshot is stale; search and explicitly review a replacement before selection",
        )
    if not payload.suitability_reviewed or not payload.pack_size_reviewed:
        raise HTTPException(
            status_code=422,
            detail="merchant must explicitly review product suitability and pack size",
        )
    if payload.kind == "consumable" and not (
        payload.shared_units or payload.per_attendee_units
    ):
        raise HTTPException(
            status_code=422,
            detail="consumable material requires shared units or units per attendee",
        )
    current = CampaignFinancialsInput.model_validate(terms.financial_inputs)
    provenance = MaterialOfferProvenanceInput(
        offer_snapshot_id=str(snapshot.id),
        provider="channel3",
        provider_product_id=snapshot.provider_product_id,
        provider_offer_ref=snapshot.provider_offer_ref,
        product_title=snapshot.product_title,
        brand_name=snapshot.brand_name,
        merchant_domain=snapshot.merchant_domain,
        reported_price_raw=snapshot.reported_price_raw,
        price_minor=snapshot.price_minor,
        currency=snapshot.currency,
        product_url=snapshot.product_url,
        image_url=snapshot.image_url,
        availability=snapshot.availability,
        condition=snapshot.condition,
        locale_country=snapshot.locale_country,
        locale_language=snapshot.locale_language,
        locale_currency=snapshot.locale_currency,
        retrieved_at=snapshot.retrieved_at,
        suitability_reviewed=payload.suitability_reviewed,
        pack_size_reviewed=payload.pack_size_reviewed,
        review_notes=payload.review_notes,
    )
    selected = MaterialLineInput(
        name=payload.material_name,
        source_label="channel3-offer-snapshot+merchant-reviewed-assumptions",
        kind=payload.kind,
        shared_units=payload.shared_units,
        per_attendee_units=payload.per_attendee_units,
        pack_size=payload.pack_size,
        pack_price_minor=snapshot.price_minor,
        offer_provenance=provenance,
    )
    materials = [line for line in current.materials if line.name != payload.material_name]
    materials.append(selected)
    updated = {
        **current.model_dump(mode="json"),
        "materials": [line.model_dump(mode="json") for line in materials],
    }
    updated["shipping_allowance_minor"] = payload.shipping_allowance_minor
    updated["shipping_allowance_source"] = payload.shipping_allowance_source
    inputs = CampaignFinancialsInput.model_validate(updated)
    CampaignTermsService(db).update_draft(terms.id, inputs)
    db.flush()

    workshop_out = WorkshopOut(
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
    return MaterialOfferSelectionOut(
        workshop=workshop_out,
        selected_offer=_offer_out(snapshot, stale_after=_stale_after(request)),
        material_line_name=payload.material_name,
        pack_price_minor=snapshot.price_minor,
        pack_size=payload.pack_size,
        shared_units=payload.shared_units,
        per_attendee_units=payload.per_attendee_units,
        shipping_allowance_minor=inputs.shipping_allowance_minor,
        shipping_allowance_source=inputs.shipping_allowance_source,
        viability_preview=_preview(inputs, terms),
    )


