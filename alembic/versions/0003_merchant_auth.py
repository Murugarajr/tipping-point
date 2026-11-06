"""merchant credentials, sessions, and campaigns

Revision ID: 0003_merchant_auth
Revises: 0002_campaign_terms
Create Date: 2026-11-06 14:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0003_merchant_auth"
down_revision: Union[str, None] = "0002_campaign_terms"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Merchant login credentials. Login identifiers are unique
    # case-insensitively; only the password HASH is ever stored.
    op.create_table(
        "merchant_credentials",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("merchant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("login_identifier", sa.String(length=100), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["merchant_id"],
            ["merchants.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("merchant_id", name="uq_merchant_credentials_merchant"),
    )
    op.create_index(
        "uq_merchant_credentials_login_lower",
        "merchant_credentials",
        [sa.text("lower(login_identifier)")],
        unique=True,
    )

    # Server-issued opaque merchant sessions. Only token and CSRF-token
    # hashes are stored, never the raw secrets.
    op.create_table(
        "merchant_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("merchant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("csrf_token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["merchant_id"],
            ["merchants.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_merchant_sessions_token_hash"),
    )
    op.create_index(
        "ix_merchant_sessions_merchant_id", "merchant_sessions", ["merchant_id"]
    )

    # Campaigns. Created at publish time in this slice with status
    # OPEN, referencing the frozen terms snapshot. One OPEN campaign
    # per workshop is enforced by a partial unique index; the full
    # campaign state machine from the plan is allowed by the check
    # constraint for later gates.
    op.create_table(
        "campaigns",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workshop_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("terms_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("cutoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("terms_version", sa.Integer(), nullable=False),
        sa.Column(
            "settlement_deadline", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workshop_id"],
            ["workshops.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["terms_id"],
            ["campaign_terms.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("terms_id", name="uq_campaigns_terms"),
        sa.CheckConstraint(
            "status IN ('DRAFT','OPEN','DECIDING','RELEASING','CANCELLED',"
            "'SETTLING','CONFIRMED','ABORTING','COMPENSATING')",
            name="ck_campaigns_status",
        ),
        sa.CheckConstraint("capacity > 0", name="ck_campaigns_capacity_positive"),
    )
    op.create_index(
        "uq_campaigns_one_open_per_workshop",
        "campaigns",
        ["workshop_id"],
        unique=True,
        postgresql_where=sa.text("status = 'OPEN'"),
    )


def downgrade() -> None:
    op.drop_table("campaigns")
    op.drop_index(
        "ix_merchant_sessions_merchant_id", table_name="merchant_sessions"
    )
    op.drop_table("merchant_sessions")
    op.drop_index(
        "uq_merchant_credentials_login_lower",
        table_name="merchant_credentials",
    )
    op.drop_table("merchant_credentials")