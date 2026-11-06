"""One-time targeted cleanup of verification run-1 leftover rows.

Deletes every campaign_terms, workshop, and merchant row in the
isolated TEST database EXCEPT the verification sentinel merchant.
This removes only rows created by the failed run-1 teardown; no schema
state and no other database is touched.
"""

import os

from sqlalchemy import delete, select

from tipping_point.db.engine import SessionLocal
from tipping_point.db.models import CampaignTerms, Merchant, Workshop
from tipping_point.db.testguard import assert_test_database_target

SENTINEL_NAME = "SENTINEL-2026-11-06-verification-preservation"


def main() -> None:
    from tipping_point.db.engine import engine

    assert_test_database_target(engine)

    with SessionLocal() as session:
        sentinel_id = session.scalars(
            select(Merchant.id).where(Merchant.name == SENTINEL_NAME)
        ).one()
        session.execute(delete(CampaignTerms))
        session.execute(delete(Workshop))
        session.execute(delete(Merchant).where(Merchant.id != sentinel_id))
        session.commit()

    with SessionLocal() as session:
        print(
            "after cleanup ->",
            "merchants:",
            len(session.scalars(select(Merchant.id)).all()),
            "workshops:",
            len(session.scalars(select(Workshop.id)).all()),
            "terms:",
            len(session.scalars(select(CampaignTerms.id)).all()),
        )


if __name__ == "__main__":
    main()