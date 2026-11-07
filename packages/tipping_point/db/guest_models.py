"""Guest reservation records; financial evidence has restrictive foreign keys."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .engine import Base


def now():
    return datetime.now(timezone.utc)


class GuestSession(Base):
    __tablename__ = "guest_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_token_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    guest_session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("guest_sessions.id", ondelete="RESTRICT"))
    campaign_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campaigns.id", ondelete="RESTRICT"))
    terms_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campaign_terms.id", ondelete="RESTRICT"))
    idempotency_key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    reservation_payload_hash: Mapped[str] = mapped_column(String(64))
    email: Mapped[str] = mapped_column(String(254))
    amount_minor: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="GBP")
    expected_payee: Mapped[str] = mapped_column(String(254))
    return_url: Mapped[str] = mapped_column(Text)
    cancel_url: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(32), default="CHECKOUT_RESERVED")
    reservation_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    provider_order_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    provider_authorization_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    provider_status: Mapped[str | None] = mapped_column(String(50))
    approve_url: Mapped[str | None] = mapped_column(Text)
    authorization_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    authorization_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    admitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    __table_args__ = (
        UniqueConstraint("guest_session_id", "idempotency_key", name="uq_bookings_guest_key"),
        CheckConstraint("amount_minor > 0 AND currency = 'GBP'", name="ck_bookings_money"),
        CheckConstraint("state IN ('CHECKOUT_RESERVED','AWAITING_APPROVAL','AUTHORIZATION_PENDING','AUTHORIZED','EXPIRED','CANCELLED','RELEASE_PENDING','VOIDED','REVIEW_REQUIRED','AUTHORIZATION_FAILED')", name="ck_bookings_state"),
        Index("ix_bookings_campaign_capacity", "campaign_id", "state", "reservation_expires_at"),
        Index("ix_bookings_guest", "guest_session_id"),
    )


class PaymentOperation(Base):
    __tablename__ = "payment_operations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    booking_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bookings.id", ondelete="RESTRICT"))
    kind: Mapped[str] = mapped_column(String(20))
    resource_scope: Mapped[str] = mapped_column(String(100), default="")
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True, default=uuid.uuid4)
    request_payload: Mapped[dict] = mapped_column(JSONB)
    request_hash: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(24), default="PREPARED")
    claim_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=0)
    provider_resource_id: Mapped[str | None] = mapped_column(String(100))
    error_code: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    __table_args__ = (
        UniqueConstraint("booking_id", "kind", "resource_scope", name="uq_payment_operations_logical"),
        CheckConstraint("kind IN ('CREATE_ORDER','AUTHORIZE','VOID')", name="ck_payment_operations_kind"),
        CheckConstraint("state IN ('PREPARED','IN_FLIGHT','SUCCEEDED','DEFINITIVELY_FAILED','UNKNOWN','PROVIDER_PENDING')", name="ck_payment_operations_state"),
    )


class BookingEvent(Base):
    """Append-only sanitized audit, including references rejected by worker fencing."""

    __tablename__ = "booking_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    booking_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bookings.id", ondelete="RESTRICT"))
    operation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("payment_operations.id", ondelete="RESTRICT"))
    kind: Mapped[str] = mapped_column(String(60))
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    __table_args__ = (Index("ix_booking_events_booking", "booking_id", "created_at"),)
