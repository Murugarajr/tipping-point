"""SQLAlchemy declarative models for the Tipping Point foundation schema."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .engine import Base


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