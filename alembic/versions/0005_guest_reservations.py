"""Guest reservations and durable Sandbox operations (additive only).

Revision ID: 0005_guest_reservations
Revises: 0004_material_costing
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0005_guest_reservations"
down_revision = "0004_material_costing"
branch_labels = None
depends_on = None


def _id():
    return sa.Column("id", UUID(as_uuid=True), primary_key=True)


def _date(name, nullable=False):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _ref(name, target, nullable=False):
    return sa.Column(name, UUID(as_uuid=True), sa.ForeignKey(target, ondelete="RESTRICT"), nullable=nullable)


def upgrade():
    op.create_table(
        "guest_sessions", _id(),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("csrf_token_hash", sa.String(64), nullable=False),
        _date("created_at"), _date("expires_at"), _date("revoked_at", True),
    )
    op.create_table(
        "bookings", _id(),
        _ref("guest_session_id", "guest_sessions.id"),
        _ref("campaign_id", "campaigns.id"), _ref("terms_id", "campaign_terms.id"),
        sa.Column("idempotency_key", UUID(as_uuid=True), nullable=False),
        sa.Column("reservation_payload_hash", sa.String(64), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("amount_minor", sa.Integer, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("expected_payee", sa.String(254), nullable=False),
        sa.Column("return_url", sa.Text, nullable=False),
        sa.Column("cancel_url", sa.Text, nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        _date("reservation_expires_at"),
        sa.Column("provider_order_id", sa.String(100), unique=True),
        sa.Column("provider_authorization_id", sa.String(100), unique=True),
        sa.Column("provider_status", sa.String(50)),
        sa.Column("approve_url", sa.Text),
        _date("authorization_created_at", True), _date("authorization_expires_at", True),
        _date("cancelled_at", True), _date("admitted_at", True), _date("created_at"), _date("updated_at"),
        sa.UniqueConstraint("guest_session_id", "idempotency_key", name="uq_bookings_guest_key"),
        sa.CheckConstraint("amount_minor > 0 AND currency = 'GBP'", name="ck_bookings_money"),
        sa.CheckConstraint("state IN ('CHECKOUT_RESERVED','AWAITING_APPROVAL','AUTHORIZATION_PENDING','AUTHORIZED','EXPIRED','CANCELLED','RELEASE_PENDING','VOIDED','REVIEW_REQUIRED','AUTHORIZATION_FAILED')", name="ck_bookings_state"),
    )
    op.create_index("ix_bookings_campaign_capacity", "bookings", ["campaign_id", "state", "reservation_expires_at"])
    op.create_index("ix_bookings_guest", "bookings", ["guest_session_id"])
    op.create_table(
        "payment_operations", _id(), _ref("booking_id", "bookings.id"),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("resource_scope", sa.String(100), nullable=False),
        sa.Column("request_id", UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("request_payload", JSONB, nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("claim_token", UUID(as_uuid=True)),
        _date("lease_expires_at", True),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("provider_resource_id", sa.String(100)),
        sa.Column("error_code", sa.String(80)),
        _date("created_at"), _date("updated_at"),
        sa.UniqueConstraint("booking_id", "kind", "resource_scope", name="uq_payment_operations_logical"),
        sa.CheckConstraint("kind IN ('CREATE_ORDER','AUTHORIZE','VOID')", name="ck_payment_operations_kind"),
        sa.CheckConstraint("state IN ('PREPARED','IN_FLIGHT','SUCCEEDED','DEFINITIVELY_FAILED','UNKNOWN','PROVIDER_PENDING')", name="ck_payment_operations_state"),
    )
    op.create_table(
        "booking_events", _id(), _ref("booking_id", "bookings.id"),
        _ref("operation_id", "payment_operations.id", True),
        sa.Column("kind", sa.String(60), nullable=False),
        sa.Column("details", JSONB, nullable=False), _date("created_at"),
    )
    op.create_index("ix_booking_events_booking", "booking_events", ["booking_id", "created_at"])
    # Preserve the exact operation request and booking expectations even if a
    # future caller accidentally attempts to mutate ORM attributes.
    op.execute("""
        CREATE FUNCTION guest_immutable_payment_request() RETURNS trigger AS $$
        BEGIN
          IF ROW(NEW.booking_id,NEW.kind,NEW.resource_scope,NEW.request_id,NEW.request_payload,NEW.request_hash)
             IS DISTINCT FROM ROW(OLD.booking_id,OLD.kind,OLD.resource_scope,OLD.request_id,OLD.request_payload,OLD.request_hash)
          THEN RAISE EXCEPTION 'payment request is immutable'; END IF;
          RETURN NEW;
        END; $$ LANGUAGE plpgsql;
        CREATE TRIGGER payment_request_immutable BEFORE UPDATE ON payment_operations
        FOR EACH ROW EXECUTE FUNCTION guest_immutable_payment_request();
        CREATE FUNCTION guest_immutable_booking_terms() RETURNS trigger AS $$
        BEGIN
          IF ROW(NEW.guest_session_id,NEW.campaign_id,NEW.terms_id,NEW.idempotency_key,
                 NEW.reservation_payload_hash,NEW.email,NEW.amount_minor,NEW.currency,
                 NEW.expected_payee,NEW.return_url,NEW.cancel_url)
             IS DISTINCT FROM ROW(OLD.guest_session_id,OLD.campaign_id,OLD.terms_id,OLD.idempotency_key,
                 OLD.reservation_payload_hash,OLD.email,OLD.amount_minor,OLD.currency,
                 OLD.expected_payee,OLD.return_url,OLD.cancel_url)
          THEN RAISE EXCEPTION 'booking expectations are immutable'; END IF;
          RETURN NEW;
        END; $$ LANGUAGE plpgsql;
        CREATE TRIGGER booking_terms_immutable BEFORE UPDATE ON bookings
        FOR EACH ROW EXECUTE FUNCTION guest_immutable_booking_terms();
    """)


def downgrade():
    raise RuntimeError("Financial evidence is retained; guest schema downgrade requires separate review")
