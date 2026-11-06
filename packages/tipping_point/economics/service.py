"""Application service for draft and frozen campaign terms.

The service validates and freezes approved terms; frozen terms are
immutable. It is exercised through tests in this slice — no HTTP
mutation endpoints exist yet because merchant authentication is not
implemented and a caller-supplied merchant ID is not authentication.
"""

from __future__ import annotations

from datetime import datetime, timezone

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db.models import CampaignTerms, MaterialOfferSnapshot, Workshop
from .calculator import (
    ALGORITHM_VERSION,
    COSTING_POLICY,
    ViabilityReport,
    build_snapshot_hash,
    calculate_viability,
)
from .errors import (
    InvalidCampaignDatesError,
    MissingAssumptionsError,
    StaleMaterialOfferError,
    TermsFrozenError,
    ZeroTicketPriceError,
)
from .schemas import CampaignFinancialsInput, CampaignScheduleInput


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _assumption_labels(inputs: CampaignFinancialsInput) -> dict:
    """Provenance labels for every input recorded in the snapshot."""
    has_channel3 = any(m.offer_provenance is not None for m in inputs.materials)
    material_provenance = {
        material.name: (
            {
                "source_label": material.source_label,
                "offer_snapshot_id": material.offer_provenance.offer_snapshot_id,
                "provider": material.offer_provenance.provider,
                "provider_product_id": material.offer_provenance.provider_product_id,
                "provider_offer_ref": material.offer_provenance.provider_offer_ref,
                "product_title": material.offer_provenance.product_title,
                "brand_name": material.offer_provenance.brand_name,
                "merchant_domain": material.offer_provenance.merchant_domain,
                "reported_price_raw": material.offer_provenance.reported_price_raw,
                "price_minor": material.offer_provenance.price_minor,
                "currency": material.offer_provenance.currency,
                "product_url": material.offer_provenance.product_url,
                "image_url": material.offer_provenance.image_url,
                "availability": material.offer_provenance.availability,
                "condition": material.offer_provenance.condition,
                "locale_country": material.offer_provenance.locale_country,
                "locale_language": material.offer_provenance.locale_language,
                "locale_currency": material.offer_provenance.locale_currency,
                "retrieved_at": material.offer_provenance.retrieved_at.isoformat(),
                "suitability_reviewed": material.offer_provenance.suitability_reviewed,
                "pack_size_reviewed": material.offer_provenance.pack_size_reviewed,
                "review_notes": material.offer_provenance.review_notes,
                "reviewed_pack_assumptions": {
                    "pack_size": material.pack_size,
                    "shared_units": material.shared_units,
                    "per_attendee_units": material.per_attendee_units,
                    "kind": material.kind,
                },
            }
            if material.offer_provenance is not None
            else {"source_label": material.source_label, "provider": None}
        )
        for material in inputs.materials
    }
    note = (
        "contains Channel3 offer snapshot provenance paired with merchant-reviewed "
        "pack, usage, and shipping assumptions; search results are not stock "
        "reservations or guaranteed delivered costs"
        if has_channel3
        else (
            "material inputs are merchant-entered/test assumptions in this "
            "slice; they are not Channel3 data and no live supplier prices "
            "were fetched"
        )
    )
    return {
        "materials": {
            material.name: material.source_label for material in inputs.materials
        },
        "material_provenance": material_provenance,
        "fee_estimate": inputs.fee_estimate.label if inputs.fee_estimate else None,
        "shipping_allowance": inputs.shipping_allowance_source,
        "contingency": "merchant-entered",
        "costing_policy": COSTING_POLICY,
        "note": note,
    }


def _report_payload(report: ViabilityReport) -> dict:
    """Serializable calculation payload stored with the snapshot."""
    return {
        "algorithm_version": report.algorithm_version,
        "currency": report.currency,
        "ticket_price_minor": report.ticket_price_minor,
        "capacity": report.capacity,
        "minimum_operating_attendance": report.minimum_operating_attendance,
        "first_viable_attendance": report.first_viable_attendance,
        "any_viable_attendance": report.any_viable_attendance,
        "is_viable_at_capacity": report.is_viable_at_capacity,
        "attendance_curve": [
            {
                "attendance": point.attendance,
                "packs_by_material": point.packs_by_material,
                "material_cost_minor": point.material_cost_minor,
                "required_budget_minor": point.required_budget_minor,
                "gross_minor": point.gross_minor,
                "estimated_fees_minor": point.estimated_fees_minor,
                "estimated_net_minor": point.estimated_net_minor,
                "estimated_surplus_minor": point.estimated_surplus_minor,
                "is_viable": point.is_viable,
            }
            for point in report.attendance_curve
        ],
    }


class CampaignTermsService:
    """Validates, persists, and freezes versioned campaign terms."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def _next_version(self, workshop_id) -> int:
        current = self._session.scalar(
            select(func.max(CampaignTerms.version)).where(
                CampaignTerms.workshop_id == workshop_id
            )
        )
        return (current or 0) + 1

    def _require_workshop(self, workshop_id) -> Workshop:
        workshop = self._session.get(Workshop, workshop_id)
        if workshop is None:
            raise LookupError(f"workshop {workshop_id} does not exist")
        return workshop

    def _refresh_row(
        self,
        row: CampaignTerms,
        financials: CampaignFinancialsInput,
        schedule: CampaignScheduleInput | None,
    ) -> None:
        report = calculate_viability(financials)
        row.currency = financials.currency
        row.financial_inputs = financials.model_dump(mode="json")
        row.assumption_labels = _assumption_labels(financials)
        row.calculation = _report_payload(report)
        row.algorithm_version = ALGORITHM_VERSION
        row.snapshot_hash = build_snapshot_hash(
            financials,
            opens_at=schedule.opens_at if schedule else row.opens_at,
            closes_at=schedule.closes_at if schedule else row.closes_at,
        )
        if schedule is not None:
            row.opens_at = schedule.opens_at
            row.closes_at = schedule.closes_at

    def create_draft(
        self,
        workshop_id,
        financials: CampaignFinancialsInput,
        schedule: CampaignScheduleInput | None = None,
    ) -> CampaignTerms:
        """Persist an incomplete draft; validation gaps may exist."""
        self._require_workshop(workshop_id)
        row = CampaignTerms(
            workshop_id=workshop_id,
            version=self._next_version(workshop_id),
        )
        self._refresh_row(row, financials, schedule)
        self._session.add(row)
        self._session.flush()
        return row

    def update_draft(
        self,
        terms_id,
        financials: CampaignFinancialsInput,
        schedule: CampaignScheduleInput | None = None,
    ) -> CampaignTerms:
        """Update an unfrozen draft; frozen terms are immutable."""
        row = self._session.get(CampaignTerms, terms_id)
        if row is None:
            raise LookupError(f"campaign terms {terms_id} do not exist")
        if row.is_frozen:
            raise TermsFrozenError(
                f"campaign terms {terms_id} are frozen and cannot be edited"
            )
        self._refresh_row(row, financials, schedule)
        self._session.flush()
        return row

    def freeze(
        self,
        terms_id,
        *,
        stale_after_seconds: int | None = None,
    ) -> CampaignTerms:
        """Validate publishable terms and freeze them immutably."""
        row = self._session.get(CampaignTerms, terms_id)
        if row is None:
            raise LookupError(f"campaign terms {terms_id} do not exist")
        if row.is_frozen:
            raise TermsFrozenError(
                f"campaign terms {terms_id} are already frozen"
            )

        inputs = CampaignFinancialsInput.model_validate(row.financial_inputs)

        if inputs.ticket_price_minor <= 0:
            raise ZeroTicketPriceError(
                "publishable terms require a ticket price above zero"
            )
        if inputs.fee_estimate is None:
            raise MissingAssumptionsError(
                "publishable terms require an explicit, reviewed "
                "fee-estimation input"
            )
        if row.opens_at is None or row.closes_at is None:
            raise MissingAssumptionsError(
                "publishable terms require campaign open and close dates"
            )

        now = _now()
        for material in inputs.materials:
            prov = material.offer_provenance
            if prov is None:
                continue
            if not prov.suitability_reviewed or not prov.pack_size_reviewed:
                raise MissingAssumptionsError(
                    f"material {material.name!r} requires explicit suitability "
                    "and pack-size review before publication"
                )
            try:
                snap_id = uuid.UUID(prov.offer_snapshot_id)
            except ValueError as exc:
                raise MissingAssumptionsError(
                    f"material {material.name!r} has an invalid offer_snapshot_id"
                ) from exc
            snapshot = self._session.get(MaterialOfferSnapshot, snap_id)
            if snapshot is None or snapshot.workshop_id != row.workshop_id:
                raise MissingAssumptionsError(
                    f"material {material.name!r} references an offer snapshot "
                    "that does not belong to this workshop"
                )
            if (
                snapshot.price_minor != prov.price_minor
                or snapshot.price_minor != material.pack_price_minor
                or snapshot.currency != prov.currency
                or snapshot.merchant_domain != prov.merchant_domain
                or snapshot.product_title != prov.product_title
            ):
                raise MissingAssumptionsError(
                    f"material {material.name!r} provenance does not match the "
                    "immutable server offer snapshot"
                )
            if stale_after_seconds is not None:
                age_seconds = (now - snapshot.retrieved_at).total_seconds()
                if age_seconds > stale_after_seconds:
                    raise StaleMaterialOfferError(
                        f"selected Channel3 offer for material {material.name!r} "
                        f"was retrieved {int(age_seconds)}s ago (stale threshold "
                        f"{stale_after_seconds}s); perform an explicit reviewed "
                        "replacement before publication"
                    )

        schedule = CampaignScheduleInput(
            opens_at=row.opens_at,
            closes_at=row.closes_at,
        )
        if row.closes_at <= now:
            raise InvalidCampaignDatesError(
                "campaign close must be in the future when terms are frozen"
            )

        # Recompute deterministically from stored inputs and verify the
        # stored snapshot still reproduces itself.
        recomputed_hash = build_snapshot_hash(
            inputs, opens_at=schedule.opens_at, closes_at=schedule.closes_at
        )
        if recomputed_hash != row.snapshot_hash:
            raise RuntimeError(
                "stored snapshot hash does not reproduce from stored inputs"
            )

        self._refresh_row(row, inputs, schedule)
        row.is_frozen = True
        row.frozen_at = _now()
        self._session.flush()
        return row