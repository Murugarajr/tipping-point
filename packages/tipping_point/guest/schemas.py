from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EmptyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GuestSessionOut(BaseModel):
    expires_at: datetime
    csrf_token: str


class ReservationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254)
    idempotency_key: UUID

    @field_validator("email")
    @classmethod
    def contact_email(cls, value):
        value = value.strip().lower()
        if value.count("@") != 1 or any(c.isspace() for c in value):
            raise ValueError("a contact email is required")
        local, domain = value.split("@")
        if not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
            raise ValueError("a contact email is required")
        return value


class BookingOut(BaseModel):
    booking_id: UUID
    campaign_id: UUID
    workshop_id: UUID
    workshop_title: str
    state: Literal[
        "CHECKOUT_RESERVED", "AWAITING_APPROVAL", "AUTHORIZATION_PENDING",
        "AUTHORIZED", "EXPIRED", "CANCELLED", "RELEASE_PENDING", "VOIDED",
        "REVIEW_REQUIRED", "AUTHORIZATION_FAILED",
    ]
    payment_state: Literal[
        "NOT_STARTED", "AWAITING_APPROVAL", "CHECKING", "AUTHORIZED",
        "RELEASE_PENDING", "VOIDED", "REVIEW_REQUIRED",
    ]
    amount_minor: int
    currency: Literal["GBP"]
    reservation_expires_at: datetime
    seat_held: bool
    approve_url: str | None
    notice: str
    can_create_order: bool
    can_authorize: bool
    can_cancel: bool
    updated_at: datetime
