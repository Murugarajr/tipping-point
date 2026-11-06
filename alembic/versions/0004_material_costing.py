"""channel3 material offer provenance snapshots

Revision ID: 0004_material_costing
Revises: 0003_merchant_auth
Create Date: 2026-11-06 16:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0004_material_costing"
down_revision: Union[str, None] = "0003_merchant_auth"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "material_offer_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("merchant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workshop_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("search_query", sa.String(length=200), nullable=False),
        sa.Column(
            "provider_product_id", sa.String(length=200), nullable=True
        ),
        sa.Column("provider_offer_ref", sa.String(length=255), nullable=False),
        sa.Column("product_title", sa.String(length=500), nullable=False),
        sa.Column("brand_name", sa.String(length=200), nullable=True),
        sa.Column("merchant_domain", sa.String(length=255), nullable=False),
        sa.Column("reported_price_raw", sa.String(length=64), nullable=False),
        sa.Column("price_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("product_url", sa.Text(), nullable=True),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("availability", sa.String(length=50), nullable=True),
        sa.Column("condition", sa.String(length=50), nullable=True),
        sa.Column("locale_country", sa.String(length=5), nullable=False),
        sa.Column("locale_language", sa.String(length=10), nullable=False),
        sa.Column("locale_currency", sa.String(length=3), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["merchant_id"],
            ["merchants.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workshop_id"],
            ["workshops.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "price_minor > 0",
            name="ck_material_offer_snapshots_price_positive",
        ),
        sa.CheckConstraint(
            "currency = 'GBP'",
            name="ck_material_offer_snapshots_currency_gbp",
        ),
        sa.CheckConstraint(
            "locale_country = 'GB' AND locale_language = 'en' AND locale_currency = 'GBP'",
            name="ck_material_offer_snapshots_locale_gb",
        ),
    )
    op.create_index(
        "ix_material_offer_snapshots_workshop_retrieved",
        "material_offer_snapshots",
        ["workshop_id", "retrieved_at"],
    )
    op.create_index(
        "ix_material_offer_snapshots_merchant_id",
        "material_offer_snapshots",
        ["merchant_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_material_offer_snapshots_merchant_id",
        table_name="material_offer_snapshots",
    )
    op.drop_index(
        "ix_material_offer_snapshots_workshop_retrieved",
        table_name="material_offer_snapshots",
    )
    op.drop_table("material_offer_snapshots")
