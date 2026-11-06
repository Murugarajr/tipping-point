"""Explicit request/response schemas for the merchant HTTP surface."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from ..economics import (
    CampaignFinancialsInput,
    CampaignScheduleInput,
)


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
    financials: CampaignFinancialsInput
    schedule: CampaignScheduleInput


class WorkshopEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    financials: CampaignFinancialsInput
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


class CampaignOut(BaseModel):
    campaign_id: str
    workshop_id: str
    status: str
    capacity: int
    cutoff_at: datetime
    terms_version: int
    terms_id: str
    terms_snapshot_hash: str