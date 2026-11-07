"""Workshop discovery visibility: additive, metadata-only, audit preserving.

Adds ``workshops.hidden_from_discovery_at`` (NULL = listed) and an append-only
``workshop_visibility_events`` audit table. Hiding only removes a workshop from
public discovery listings; it never changes campaign, terms, booking, payment
or settlement state, and it is not an access-control boundary.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0007_workshop_visibility"
down_revision = "0006_campaign_settlement"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("workshops", sa.Column("hidden_from_discovery_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "workshop_visibility_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("workshop_id", UUID(as_uuid=True), sa.ForeignKey("workshops.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("merchant_id", UUID(as_uuid=True), sa.ForeignKey("merchants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("previous_hidden_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hidden_from_discovery_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("action IN ('HIDE','RESTORE')", name="ck_visibility_event_action"),
        sa.CheckConstraint(
            "(action = 'HIDE' AND hidden_from_discovery_at IS NOT NULL)"
            " OR (action = 'RESTORE' AND hidden_from_discovery_at IS NULL)",
            name="ck_visibility_event_state",
        ),
    )
    op.create_index("ix_visibility_events_workshop", "workshop_visibility_events", ["workshop_id", "occurred_at"])


def downgrade():
    raise RuntimeError("Visibility audit evidence is retained; downgrade needs separate review")
