"""Validated input schemas for workshop economics.

All money is integer minor units (GBP pence). Unsupported currencies,
invalid quantities, and invalid money are rejected at the schema boundary.
Material inputs carry explicit provenance labels; this slice never treats
merchant-entered or test inputs as Channel3 data.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field, model_validator

Currency = Literal["GBP"]

#: Approved short-duration booking-campaign policy (application policy,
#: deliberately shorter than the PayPal three-day honor window).
CAMPAIGN_MAX_DURATION_HOURS = 48


class FeeEstimateInput(BaseModel):
    """Explicit conservative payment-fee estimate.

    ``percent_basis_points`` is hundredths of a percent (249 = 2.49%).
    The variable part of each transaction fee is rounded UP, which is the
    conservative direction for net-revenue estimates. This is an
    estimate input, not a merchant's real fee schedule.
    """

    percent_basis_points: int = Field(ge=0, le=10000)
    fixed_minor: int = Field(ge=0)
    label: str = Field(
        default="merchant-entered-conservative-estimate",
        min_length=1,
        max_length=100,
    )


class MaterialOfferProvenanceInput(BaseModel):
    """Server-bound Channel3 offer provenance and reviewed pack assumptions."""

    model_config = {"extra": "forbid"}

    offer_snapshot_id: str = Field(min_length=1, max_length=64)
    provider: Literal["channel3"] = "channel3"
    provider_product_id: str | None = Field(default=None, max_length=200)
    provider_offer_ref: str = Field(min_length=1, max_length=255)
    product_title: str = Field(min_length=1, max_length=500)
    brand_name: str | None = Field(default=None, max_length=200)
    merchant_domain: str = Field(min_length=1, max_length=255)
    reported_price_raw: str = Field(min_length=1, max_length=64)
    price_minor: int = Field(ge=1)
    currency: Currency = "GBP"
    product_url: str | None = Field(default=None, max_length=2000)
    image_url: str | None = Field(default=None, max_length=2000)
    availability: str | None = Field(default=None, max_length=50)
    condition: str | None = Field(default=None, max_length=50)
    locale_country: Literal["GB"] = "GB"
    locale_language: Literal["en"] = "en"
    locale_currency: Currency = "GBP"
    retrieved_at: datetime
    suitability_reviewed: bool = True
    pack_size_reviewed: bool = True
    review_notes: str | None = Field(default=None, max_length=500)


class MaterialLineInput(BaseModel):
    """One material line with explicit provenance.

    Consumable lines are budgeted via whole packs. Reusable equipment is
    recorded as an assumption but is not budgeted (see COSTING_POLICY).
    """

    model_config = {"extra": "forbid"}

    name: str = Field(min_length=1, max_length=200)
    source_label: str = Field(min_length=1, max_length=100)
    kind: Literal["consumable", "reusable"] = "consumable"
    shared_units: int = Field(ge=0)
    per_attendee_units: int = Field(ge=0)
    pack_size: int = Field(ge=1)
    pack_price_minor: int = Field(ge=0)
    offer_provenance: MaterialOfferProvenanceInput | None = None

    @model_validator(mode="after")
    def _require_units_for_consumables(self) -> "MaterialLineInput":
        if self.kind == "consumable" and self.shared_units == 0 and self.per_attendee_units == 0:
            raise ValueError(
                f"consumable material {self.name!r} requires shared or per-attendee units"
            )
        if self.offer_provenance is not None:
            if self.pack_price_minor != self.offer_provenance.price_minor:
                raise ValueError(
                    "material line pack_price_minor must equal the selected offer snapshot price_minor"
                )
        return self


class CampaignFinancialsInput(BaseModel):
    """Financial inputs for a workshop campaign draft.

    Drafts may be incomplete (zero ticket price, absent fee estimate).
    Publishable terms additionally require a positive ticket price and a
    fee estimate; that enforcement lives in the terms service.
    """

    model_config = {"extra": "forbid"}

    currency: Currency = "GBP"
    ticket_price_minor: int = Field(ge=0)
    capacity: int = Field(ge=1)
    minimum_operating_attendance: int | None = Field(default=None, ge=1)
    fixed_costs_minor: int = Field(default=0, ge=0)
    materials: list[MaterialLineInput] = Field(default_factory=list)
    shipping_allowance_minor: int = Field(default=0, ge=0)
    shipping_allowance_source: str = Field(
        default="merchant-entered",
        min_length=1,
        max_length=120,
    )
    contingency_minor: int = Field(default=0, ge=0)
    fee_estimate: FeeEstimateInput | None = None

    @model_validator(mode="after")
    def _validate(self) -> "CampaignFinancialsInput":
        names = [material.name for material in self.materials]
        if len(names) != len(set(names)):
            raise ValueError("material names must be unique")
        if (
            self.minimum_operating_attendance is not None
            and self.minimum_operating_attendance > self.capacity
        ):
            raise ValueError(
                "minimum_operating_attendance cannot exceed capacity "
                f"({self.minimum_operating_attendance} > {self.capacity})"
            )
        return self


class CampaignScheduleInput(BaseModel):
    """Campaign booking window with the approved short-duration policy."""

    model_config = {"extra": "forbid"}

    opens_at: datetime
    closes_at: datetime

    @model_validator(mode="after")
    def _validate(self) -> "CampaignScheduleInput":
        if self.opens_at.tzinfo is None or self.closes_at.tzinfo is None:
            raise ValueError("campaign dates must be timezone-aware")
        if self.closes_at <= self.opens_at:
            raise ValueError("campaign close must be after campaign open")
        if self.closes_at - self.opens_at > timedelta(hours=CAMPAIGN_MAX_DURATION_HOURS):
            raise ValueError(
                "campaign duration exceeds the approved short-duration policy "
                f"of {CAMPAIGN_MAX_DURATION_HOURS} hours"
            )
        return self