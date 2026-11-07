"""Durable deadline cohorts, settlement resources and dispatch (audit preserving)."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0006_campaign_settlement"
down_revision = "0005_guest_reservations"
branch_labels = None
depends_on = None


def ident():
    return sa.Column("id", UUID(as_uuid=True), primary_key=True)


def ref(name, target, **kwargs):
    return sa.Column(name, UUID(as_uuid=True), sa.ForeignKey(target, ondelete="RESTRICT"), nullable=False, **kwargs)


def upgrade():
    op.create_table(
        "campaign_decisions", ident(), ref("campaign_id", "campaigns.id", unique=True),
        ref("terms_id", "campaign_terms.id"),
        sa.Column("terms_version", sa.Integer, nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("frozen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attendance", sa.Integer, nullable=False),
        sa.Column("result", sa.String(24), nullable=False),
        sa.Column("reason", sa.String(100), nullable=False),
        sa.Column("evidence", JSONB, nullable=False),
        sa.Column("policy", JSONB, nullable=False),
        sa.Column("settlement_deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("review_required", sa.Boolean, nullable=False),
        sa.Column("post_collection", JSONB, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("attendance >= 0", name="ck_decision_attendance"),
        sa.CheckConstraint("result IN ('COLLECT','RELEASE','REVIEW_REQUIRED')", name="ck_decision_result"),
    )
    op.create_table(
        "decision_cohort_members", ident(), ref("decision_id", "campaign_decisions.id"),
        ref("booking_id", "bookings.id", unique=True),
        sa.Column("order_id", sa.String(100), nullable=False),
        sa.Column("authorization_id", sa.String(100), nullable=False),
        sa.Column("amount_minor", sa.Integer, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("capture_id", sa.String(100), unique=True),
        sa.Column("capture_status", sa.String(32)),
        sa.Column("refund_id", sa.String(100), unique=True),
        sa.Column("refund_status", sa.String(32)),
        sa.Column("actual_fee_minor", sa.Integer),
        sa.Column("capture_observation", JSONB, nullable=False),
        sa.Column("refund_observation", JSONB, nullable=False),
        sa.UniqueConstraint("decision_id", "booking_id", name="uq_cohort_decision_booking"),
        sa.CheckConstraint("amount_minor > 0 AND currency = 'GBP'", name="ck_cohort_money"),
    )
    op.create_table(
        "settlement_work", ident(), ref("campaign_id", "campaigns.id", unique=True),
        sa.Column("purpose", sa.String(24), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("claim_token", UUID(as_uuid=True)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False),
        sa.Column("last_error", sa.String(100)),
        sa.CheckConstraint("state IN ('READY','LEASED','DONE')", name="ck_settlement_work_state"),
    )
    op.create_index("ix_settlement_work_due", "settlement_work", ["state", "due_at"])
    op.drop_constraint("ck_bookings_state", "bookings", type_="check")
    op.create_check_constraint("ck_bookings_state", "bookings", "state IN ('CHECKOUT_RESERVED','AWAITING_APPROVAL','AUTHORIZATION_PENDING','AUTHORIZED','EXPIRED','CANCELLED','RELEASE_PENDING','VOIDED','REVIEW_REQUIRED','AUTHORIZATION_FAILED','CAPTURE_PENDING','PAID','REFUND_PENDING','REFUNDED')")
    op.drop_constraint("ck_payment_operations_kind", "payment_operations", type_="check")
    op.create_check_constraint("ck_payment_operations_kind", "payment_operations", "kind IN ('CREATE_ORDER','AUTHORIZE','VOID','CAPTURE','REFUND')")
    op.execute("""
    CREATE FUNCTION settlement_frozen_evidence() RETURNS trigger AS $$
    BEGIN
      IF TG_TABLE_NAME = 'campaign_decisions' THEN
        IF (to_jsonb(NEW) - ARRAY['review_required','post_collection','updated_at'])
           IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['review_required','post_collection','updated_at'])
        THEN RAISE EXCEPTION 'deadline decision evidence is immutable'; END IF;
      ELSE
        IF ROW(NEW.decision_id,NEW.booking_id,NEW.order_id,NEW.authorization_id,NEW.amount_minor,NEW.currency)
          IS DISTINCT FROM ROW(OLD.decision_id,OLD.booking_id,OLD.order_id,OLD.authorization_id,OLD.amount_minor,OLD.currency)
        THEN RAISE EXCEPTION 'frozen cohort is immutable'; END IF;
        IF (OLD.capture_id IS NOT NULL AND NEW.capture_id IS DISTINCT FROM OLD.capture_id)
          OR (OLD.refund_id IS NOT NULL AND NEW.refund_id IS DISTINCT FROM OLD.refund_id)
        THEN RAISE EXCEPTION 'financial references are retained'; END IF;
      END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql;
    CREATE TRIGGER decision_evidence_immutable BEFORE UPDATE ON campaign_decisions
      FOR EACH ROW EXECUTE FUNCTION settlement_frozen_evidence();
    CREATE TRIGGER cohort_expectations_immutable BEFORE UPDATE ON decision_cohort_members
      FOR EACH ROW EXECUTE FUNCTION settlement_frozen_evidence();
    """)


def downgrade():
    raise RuntimeError("Settlement financial evidence is retained; downgrade needs separate review")
