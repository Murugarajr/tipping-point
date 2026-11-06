"""Application service for draft and frozen campaign terms.

The service validates and freezes approved terms; frozen terms are
immutable. It is exercised through tests in this slice — no HTTP
mutation endpoints exist yet because merchant authentication is not
implemented and a caller-supplied merchant ID is not authentication.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db.models import CampaignTerms, Workshop
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
    TermsFrozenError,
    ZeroTicketPriceError,
)
from .schemas import CampaignFinancialsInput, CampaignScheduleInput


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _assumption_labels(inputs: CampaignFinancialsInput) -> dict:
    """Provenance labels for every input this slice records."""
    return {
        "materials": {
            material.name: material.source_label for material in inputs.materials
        },
        "fee_estimate": inputs.fee_estimate.label if inputs.fee_estimate else None,
        "shipping_allowance": "merchant-entered",
        "contingency": "merchant-entered",
        "costing_policy": COSTING_POLICY,
        "note": (
            "material inputs are merchant-entered/test assumptions in this "
            "slice; they are not Channel3 data and no live supplier prices "
            "were fetched"
        ),
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

    def freeze(self, terms_id) -> CampaignTerms:
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

        schedule = CampaignScheduleInput(
            opens_at=row.opens_at,
            closes_at=row.closes_at,
        )
        if row.closes_at <= _now():
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