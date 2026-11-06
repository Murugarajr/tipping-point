"""campaign terms and merchant restrict

Revision ID: 0002_campaign_terms
Revises: 0001_initial_merchant_workshop
Create Date: 2026-11-06 12:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002_campaign_terms"
down_revision: Union[str, None] = "0001_initial_merchant_workshop"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Additive: versioned campaign terms snapshots.
    op.create_table(
        "campaign_terms",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workshop_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("financial_inputs", postgresql.JSONB(), nullable=False),
        sa.Column("assumption_labels", postgresql.JSONB(), nullable=False),
        sa.Column("calculation", postgresql.JSONB(), nullable=False),
        sa.Column("algorithm_version", sa.String(length=50), nullable=False),
        sa.Column("snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("opens_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closes_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_frozen", sa.Boolean(), nullable=False),
        sa.Column("frozen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workshop_id"],
            ["workshops.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workshop_id", "version", name="uq_campaign_terms_workshop_version"
        ),
        sa.CheckConstraint(
            "currency = 'GBP'", name="ck_campaign_terms_currency_gbp"
        ),
    )
    # Prevent destructive cascade deletion of merchant rows that still own
    # workshops (payment/campaign evidence must never be orphaned silently).
    op.drop_constraint("workshops_merchant_id_fkey", "workshops", type_="foreignkey")
    op.create_foreign_key(
        "workshops_merchant_id_fkey",
        "workshops",
        "merchants",
        ["merchant_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint("workshops_merchant_id_fkey", "workshops", type_="foreignkey")
    op.create_foreign_key(
        "workshops_merchant_id_fkey",
        "workshops",
        "merchants",
        ["merchant_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_table("campaign_terms")