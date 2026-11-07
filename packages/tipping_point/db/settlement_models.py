"""Deadline evidence and due work; payment operations remain in the guest ledger."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .engine import Base
from .guest_models import now


class CampaignDecision(Base):
    __tablename__ = "campaign_decisions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campaigns.id", ondelete="RESTRICT"), unique=True)
    terms_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campaign_terms.id", ondelete="RESTRICT"))
    terms_version: Mapped[int] = mapped_column(Integer)
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    frozen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    attendance: Mapped[int] = mapped_column(Integer)
    result: Mapped[str] = mapped_column(String(24))
    reason: Mapped[str] = mapped_column(String(100))
    evidence: Mapped[dict] = mapped_column(JSONB)
    policy: Mapped[dict] = mapped_column(JSONB)
    settlement_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    review_required: Mapped[bool] = mapped_column(Boolean, default=False)
    post_collection: Mapped[dict] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    __table_args__ = (
        CheckConstraint("attendance >= 0", name="ck_decision_attendance"),
        CheckConstraint("result IN ('COLLECT','RELEASE','REVIEW_REQUIRED')", name="ck_decision_result"),
    )


class DecisionCohortMember(Base):
    __tablename__ = "decision_cohort_members"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    decision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campaign_decisions.id", ondelete="RESTRICT"))
    booking_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bookings.id", ondelete="RESTRICT"), unique=True)
    order_id: Mapped[str] = mapped_column(String(100))
    authorization_id: Mapped[str] = mapped_column(String(100))
    amount_minor: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    capture_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    capture_status: Mapped[str | None] = mapped_column(String(32))
    refund_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    refund_status: Mapped[str | None] = mapped_column(String(32))
    actual_fee_minor: Mapped[int | None] = mapped_column(Integer)
    capture_observation: Mapped[dict] = mapped_column(JSONB, default=dict)
    refund_observation: Mapped[dict] = mapped_column(JSONB, default=dict)
    __table_args__ = (
        UniqueConstraint("decision_id", "booking_id", name="uq_cohort_decision_booking"),
        CheckConstraint("amount_minor > 0 AND currency = 'GBP'", name="ck_cohort_money"),
    )


class SettlementWork(Base):
    __tablename__ = "settlement_work"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campaigns.id", ondelete="RESTRICT"), unique=True)
    purpose: Mapped[str] = mapped_column(String(24), default="DEADLINE")
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(String(16), default="READY")
    claim_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(100))
    __table_args__ = (
        Index("ix_settlement_work_due", "state", "due_at"),
        CheckConstraint("state IN ('READY','LEASED','DONE')", name="ck_settlement_work_state"),
    )
