from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import uuid

import pytest

from tipping_point.api.public_routes import _public_workshop


@pytest.mark.parametrize("offset,status,expected", [
    (-1, "OPEN", "not_open_yet"), (0, "OPEN", "open"),
    (1, "OPEN", "closed"), (0, "CONFIRMED", "unavailable"),
    (0, "CANCELLED", "unavailable"),
])
def test_window_is_separate_from_reservation_and_payment_capability(offset, status, expected):
    now = datetime.now(timezone.utc)
    workshop = SimpleNamespace(id=uuid.uuid4(), title="Public copy", description="Description")
    campaign = SimpleNamespace(id=uuid.uuid4(), status=status)
    terms = SimpleNamespace(
        opens_at=now, closes_at=now + timedelta(hours=1),
        financial_inputs={"currency": "GBP", "ticket_price_minor": 5000, "capacity": 8},
    )
    projected = _public_workshop(workshop, campaign, terms, now=now + timedelta(hours=offset))
    assert projected.booking_window_status == expected
    assert projected.reservations_available is False
    assert "not enabled" in projected.availability_note
    assert "financial_inputs" not in projected.model_dump()
