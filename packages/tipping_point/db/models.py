"""SQLAlchemy declarative models for the Tipping Point foundation schema."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .engine import Base
from .guest_models import Booking, BookingEvent, GuestSession, PaymentOperation
from .settlement_models import CampaignDecision, DecisionCohortMember, SettlementWork


def _utcnow() -> datetime:
    """Return a timezone-aware UTC timestamp for new rows."""
    return datetime.now(timezone.utc)


def _generate_uuid() -> uuid.UUID:
    """Generate a new UUID for identifiers."""
    return uuid.uuid4()


class Merchant(Base):
    """A workshop host (the single MVP merchant)."""

    __tablename__ = "merchants"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=_generate_uuid,
    )
    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("name", name="uq_merchant_name"),
    )


class Workshop(Base):
    """A workshop owned by a merchant."""

    __tablename__ = "workshops"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=_generate_uuid,
    )
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("merchants.id", ondelete="RESTRICT"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    capacity: Mapped[int] = mapped_column(
        nullable=False,
    )
    ticket_price_minor: Mapped[int] = mapped_column(
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="GBP",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint("capacity > 0", name="ck_workshop_capacity_positive"),
        CheckConstraint(
            "ticket_price_minor >= 0",
            name="ck_workshop_ticket_price_non_negative",
        ),
    )


class CampaignTerms(Base):
    """Versioned, immutable-once-frozen campaign terms snapshot.

    Drafts (``is_frozen=False``) may be incomplete and are editable.
    Frozen rows are immutable in the application service; a material
    change requires the approved cancellation/new-campaign path.
    """

    __tablename__ = "campaign_terms"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=_generate_uuid,
    )
    workshop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workshops.id", ondelete="RESTRICT"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="GBP",
    )
    financial_inputs: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
    )
    assumption_labels: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
    )
    calculation: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
    )
    algorithm_version: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    snapshot_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    opens_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    closes_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    is_frozen: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    frozen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("workshop_id", "version", name="uq_campaign_terms_workshop_version"),
        CheckConstraint("currency = 'GBP'", name="ck_campaign_terms_currency_gbp"),
    )


class MerchantCredential(Base):
    """Login credentials for a merchant.

    Only the password hash is stored. A merchant without a credential
    row cannot log in. One credential per merchant.
    """

    __tablename__ = "merchant_credentials"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_generate_uuid
    )
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("merchants.id", ondelete="RESTRICT"),
        nullable=False,
    )
    login_identifier: Mapped[str] = mapped_column(String(100), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("merchant_id", name="uq_merchant_credentials_merchant"),
        Index(
            "uq_merchant_credentials_login_lower",
            text("lower(login_identifier)"),
            unique=True,
        ),
    )


class MerchantSession(Base):
    """A server-issued opaque merchant session.

    Stores only SHA-256 hashes of the session token and the bound CSRF
    token; the raw secrets exist only in the cookie/response.
    """

    __tablename__ = "merchant_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_generate_uuid
    )
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("merchants.id", ondelete="RESTRICT"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    csrf_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_merchant_sessions_token_hash"),
        Index("ix_merchant_sessions_merchant_id", "merchant_id"),
    )


class Campaign(Base):
    """A workshop campaign.

    Created at publish time in this slice with status OPEN and an
    authoritative reference to the frozen terms snapshot. One OPEN
    campaign per workshop (partial unique index). The plan's full
    campaign state machine is permitted by the status check constraint;
    later gates perform the remaining transitions.
    """

    __tablename__ = "campaigns"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_generate_uuid
    )
    workshop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workshops.id", ondelete="RESTRICT"),
        nullable=False,
    )
    terms_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("campaign_terms.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN")
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    cutoff_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    terms_version: Mapped[int] = mapped_column(Integer, nullable=False)
    settlement_deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("terms_id", name="uq_campaigns_terms"),
        CheckConstraint(
            "status IN ('DRAFT','OPEN','DECIDING','RELEASING','CANCELLED',"
            "'SETTLING','CONFIRMED','ABORTING','COMPENSATING')",
            name="ck_campaigns_status",
        ),
        CheckConstraint("capacity > 0", name="ck_campaigns_capacity_positive"),
        Index(
            "uq_campaigns_one_open_per_workshop",
            "workshop_id",
            unique=True,
            postgresql_where=text("status = 'OPEN'"),
        ),
    )


class MaterialOfferSnapshot(Base):
    """Immutable server-stored Channel3 offer provenance snapshot.

    Created when a merchant searches material offers for an owned
    workshop. Never overwritten in place once persisted, so price
    snapshots referenced by draft or frozen workshop terms retain their
    original provider facts and retrieval timestamp.
    """

    __tablename__ = "material_offer_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_generate_uuid
    )
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("merchants.id", ondelete="RESTRICT"),
        nullable=False,
    )
    workshop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workshops.id", ondelete="RESTRICT"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(
        String(30), nullable=False, default="channel3"
    )
    search_query: Mapped[str] = mapped_column(String(200), nullable=False)
    provider_product_id: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )
    provider_offer_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    product_title: Mapped[str] = mapped_column(String(500), nullable=False)
    brand_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    merchant_domain: Mapped[str] = mapped_column(String(255), nullable=False)
    reported_price_raw: Mapped[str] = mapped_column(String(64), nullable=False)
    price_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="GBP"
    )
    product_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    availability: Mapped[str | None] = mapped_column(String(50), nullable=True)
    condition: Mapped[str | None] = mapped_column(String(50), nullable=True)
    locale_country: Mapped[str] = mapped_column(
        String(5), nullable=False, default="GB"
    )
    locale_language: Mapped[str] = mapped_column(
        String(10), nullable=False, default="en"
    )
    locale_currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="GBP"
    )
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "price_minor > 0", name="ck_material_offer_snapshots_price_positive"
        ),
        CheckConstraint(
            "currency = 'GBP'", name="ck_material_offer_snapshots_currency_gbp"
        ),
        CheckConstraint(
            "locale_country = 'GB' AND locale_language = 'en' AND locale_currency = 'GBP'",
            name="ck_material_offer_snapshots_locale_gb",
        ),
        Index(
            "ix_material_offer_snapshots_workshop_retrieved",
            "workshop_id",
            "retrieved_at",
        ),
        Index(
            "ix_material_offer_snapshots_merchant_id",
            "merchant_id",
        ),
    )
