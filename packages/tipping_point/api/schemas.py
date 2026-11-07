"""Explicit request/response schemas for the merchant HTTP surface."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..economics import (
    CampaignFinancialsInput,
    CampaignScheduleInput,
    MaterialLineInput,
)


class MerchantMaterialInput(MaterialLineInput):
    """Manual assumptions or a reference to an already reviewed server line."""

    selected_offer_snapshot_id: str | None = Field(default=None, max_length=64)


class MerchantFinancialsInput(CampaignFinancialsInput):
    """Merchant-supplied terms with no client-controlled offer provenance."""

    materials: list[MerchantMaterialInput] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _reject_client_offer_provenance(cls, value):
        if isinstance(value, dict):
            for material in value.get("materials", []):
                if isinstance(material, dict) and "offer_provenance" in material:
                    raise ValueError(
                        "offer provenance must be selected from a server-stored offer ID"
                    )
        return value


class LoginRequest(BaseModel):
    """Login credentials. Never includes merchant IDs or roles."""

    model_config = ConfigDict(extra="forbid")

    login_identifier: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=1, max_length=1024)


class MerchantInfo(BaseModel):
    merchant_id: str
    name: str


class SessionInfo(BaseModel):
    """Current session description (no secrets)."""

    merchant: MerchantInfo
    session_id: str
    expires_at: datetime
    csrf_token: str


class CsrfBootstrap(BaseModel):
    csrf_token: str


class WorkshopCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    financials: MerchantFinancialsInput
    schedule: CampaignScheduleInput


class WorkshopEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    financials: MerchantFinancialsInput
    schedule: CampaignScheduleInput


class AttendancePointOut(BaseModel):
    attendance: int
    packs_by_material: dict[str, int]
    material_cost_minor: int
    required_budget_minor: int
    gross_minor: int
    estimated_fees_minor: int
    estimated_net_minor: int
    estimated_surplus_minor: int
    is_viable: bool


class ViabilityPreviewOut(BaseModel):
    """Preview result; surpluses are ESTIMATES, never audited profit."""

    algorithm_version: str
    terms_version: int
    terms_snapshot_hash: str
    currency: str
    ticket_price_minor: int
    capacity: int
    minimum_operating_attendance: int
    first_viable_attendance: int | None
    any_viable_attendance: bool
    is_viable_at_capacity: bool
    attendance_curve: list[AttendancePointOut]
    materials_note: str = (
        "material inputs are merchant-entered assumptions; they are not "
        "Channel3 data and no live supplier prices were fetched"
    )


class WorkshopOut(BaseModel):
    workshop_id: str
    title: str
    description: str | None
    capacity: int
    ticket_price_minor: int
    currency: str
    terms_version: int
    is_frozen: bool
    opens_at: datetime | None
    closes_at: datetime | None
    campaign_id: str | None = None
    # Discovery-listing metadata only; NULL means listed in public browsing.
    hidden_from_discovery_at: datetime | None = None


class WorkshopVisibilityOut(BaseModel):
    """Result of Hide from discovery / Restore visibility (listing metadata only)."""

    workshop_id: str
    hidden_from_discovery_at: datetime | None
    changed: bool


class SandboxCleanupStatusOut(BaseModel):
    """Approved Sandbox operator-test cleanup only; never a general refund policy."""

    status: Literal["REFUND_PROCESSING", "REFUNDED", "REVIEW_REQUIRED"]
    reason: str | None
    requested_at: datetime | None
    previously_confirmed: bool
    review_reason: str | None


class SettlementStatusOut(BaseModel):
    state: str
    decision_result: Literal["COLLECT", "RELEASE", "REVIEW_REQUIRED"] | None
    decision_reason: str | None
    frozen_attendance: int | None
    admitted_attendance: int
    authorized_minor: int
    collected_minor: int
    refunded_minor: int
    net_collected_minor: int = 0
    capture_pending: int
    release_pending: int
    refund_pending: int
    review_required: bool
    settlement_deadline: datetime | None
    fee_basis: Literal["estimated", "actual", "mixed"]
    actual_fees_minor: int | None
    estimated_fees_minor: int | None
    estimated_surplus_minor: int | None
    post_collection_surplus_minor: int | None
    sandbox_cleanup: SandboxCleanupStatusOut | None = None


class CampaignOut(BaseModel):
    campaign_id: str
    workshop_id: str
    status: str
    capacity: int
    cutoff_at: datetime
    terms_version: int
    terms_id: str
    terms_snapshot_hash: str
    settlement: SettlementStatusOut | None = None


class WorkshopDetailOut(WorkshopOut):
    """Private owner-only saved inputs; never a public endpoint response."""

    financials: CampaignFinancialsInput
    terms_snapshot_hash: str
    campaign: CampaignOut | None
    offer_stale_after_seconds: int


class PublishReviewRequest(BaseModel):
    """Expected saved terms reviewed by the browser, not financial authority."""

    model_config = ConfigDict(extra="forbid")
    expected_terms_version: int = Field(ge=1)
    expected_terms_snapshot_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class PublicWorkshopOut(BaseModel):
    """Deliberately public metadata, not a terms/ORM serialization."""

    workshop_id: str
    campaign_id: str
    title: str
    description: str | None
    currency: Literal["GBP"]
    ticket_price_minor: int
    capacity: int
    opens_at: datetime
    cutoff_at: datetime
    publication_status: str
    booking_window_status: Literal["not_open_yet", "open", "closed", "unavailable"]
    reservations_available: bool = False
    availability_reason: Literal[
        "available", "not_open_yet", "closed", "full", "payment_unconfigured",
        "ineligible", "schema_unavailable",
    ] = "payment_unconfigured"
    available_seats: int | None = None
    availability_note: str = "Guest reservations and payments are not enabled in this prototype."


class MaterialOfferSearchRequest(BaseModel):
    """Bounded Channel3 product search request for a workshop draft."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=10, ge=1, le=20)
    in_stock_only: bool = True


class MaterialOfferSnapshotOut(BaseModel):
    """Server-persisted Channel3 offer provenance snapshot."""

    offer_snapshot_id: str
    workshop_id: str
    provider: str
    search_query: str
    provider_product_id: str | None
    provider_offer_ref: str
    product_title: str
    brand_name: str | None
    merchant_domain: str
    reported_price_raw: str
    price_minor: int
    currency: str
    product_url: str | None
    image_url: str | None
    availability: str | None
    condition: str | None
    locale_country: str
    locale_language: str
    locale_currency: str
    retrieved_at: datetime
    is_stale: bool
    freshness_label: str
    limitations_note: str = (
        "Channel3 search results are not stock reservations, guaranteed "
        "delivered prices, verified pack quantities, or shipping-time guarantees."
    )


class RejectedOfferCandidateOut(BaseModel):
    """Provider offer rejected for automatic costing (e.g. non-GBP or invalid price)."""

    provider_product_id: str | None
    provider_offer_ref: str
    product_title: str
    merchant_domain: str
    reported_price_raw: str | None
    currency: str | None
    ineligible_reason: str


class MaterialOfferSearchResponseOut(BaseModel):
    """Search response separating fresh/persisted offers from rejected candidates."""

    workshop_id: str
    query: str
    locale_country: str
    locale_language: str
    locale_currency: str
    retrieved_at: datetime
    offers: list[MaterialOfferSnapshotOut]
    rejected_offers: list[RejectedOfferCandidateOut]
    eligible_count: int
    rejected_count: int


class MaterialOfferSelectionRequest(BaseModel):
    """Select a server-stored offer snapshot and record reviewed assumptions.

    Forbids caller-supplied ``price_minor``, ``pack_price_minor``,
    ``merchant_domain``, ``currency``, or raw provider provenance fields.
    """

    model_config = ConfigDict(extra="forbid")

    offer_snapshot_id: str = Field(min_length=1, max_length=64)
    material_name: str = Field(min_length=1, max_length=200)
    kind: str = Field(default="consumable", pattern="^(consumable|reusable)$")
    pack_size: int = Field(ge=1)
    shared_units: int = Field(ge=0)
    per_attendee_units: int = Field(ge=0)
    suitability_reviewed: bool
    pack_size_reviewed: bool
    review_notes: str | None = Field(default=None, max_length=500)
    shipping_allowance_minor: int = Field(ge=0)
    shipping_allowance_source: str = Field(min_length=1, max_length=120)


class MaterialOfferSelectionOut(BaseModel):
    """Result of selecting a Channel3 offer snapshot into the draft."""

    workshop: WorkshopOut
    selected_offer: MaterialOfferSnapshotOut
    material_line_name: str
    pack_price_minor: int
    pack_size: int
    shared_units: int
    per_attendee_units: int
    shipping_allowance_minor: int
    shipping_allowance_source: str
    viability_preview: ViabilityPreviewOut
