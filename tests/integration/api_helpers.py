"""Shared helpers for the authenticated API integration tests.

Creates merchants with TEST credentials directly in the database
(registered in the ``owned`` registry) and drives the REAL
authentication flow through TestClient — never by overriding the
authentication dependency.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from tipping_point.app import app as default_app
from tipping_point.auth.passwords import hash_password
from tipping_point.db.models import Merchant, MerchantCredential
from tipping_point.db.session import SessionLocal


def create_merchant_with_credentials(
    owned,
    *,
    name: str | None = None,
    login: str | None = None,
    password: str = "correct-horse-battery-test",
) -> tuple[uuid.UUID, str, str]:
    """Create a merchant plus test credentials; returns (id, login, password)."""
    login = login or f"merchant-{uuid.uuid4().hex[:12]}"
    name = name or f"Merchant {uuid.uuid4().hex[:8]}"
    merchant_id = uuid.uuid4()
    with SessionLocal() as session:
        session.add(Merchant(id=merchant_id, name=name))
        session.flush()
        session.add(
            MerchantCredential(
                id=uuid.uuid4(),
                merchant_id=merchant_id,
                login_identifier=login,
                password_hash=hash_password(password),
            )
        )
        session.commit()
    owned.add(Merchant, merchant_id)
    return merchant_id, login, password


def login_client(
    client: TestClient,
    login: str,
    password: str,
    *,
    origin: str | None = None,
) -> tuple[int, dict]:
    """Drive the real bootstrap + login flow; returns (status, json)."""
    bootstrap = client.get("/api/auth/csrf")
    csrf = bootstrap.json()["csrf_token"]
    headers = {"X-CSRF-Token": csrf}
    if origin:
        headers["Origin"] = origin
    response = client.post(
        "/api/merchant/login",
        json={"login_identifier": login, "password": password},
        headers=headers,
    )
    return response.status_code, (response.json() if response.status_code == 200 else {})


def logged_in_client(owned, app=default_app) -> tuple[TestClient, dict]:
    """A TestClient with a real authenticated session; returns (client, info)."""
    merchant_id, login, password = create_merchant_with_credentials(owned)
    client = TestClient(app)
    status, info = login_client(client, login, password)
    assert status == 200, info
    return client, {
        "merchant_id": merchant_id,
        "login": login,
        "password": password,
        "csrf": info["csrf_token"],
        "client": client,
    }


def get_csrf_for(client: TestClient) -> str:
    """Fetch the (anonymous) CSRF bootstrap token."""
    return client.get("/api/auth/csrf").json()["csrf_token"]


def count_sessions_for(merchant_id) -> int:
    from tipping_point.db.models import MerchantSession

    with SessionLocal() as session:
        return len(
            session.scalars(
                select(MerchantSession.id).where(
                    MerchantSession.merchant_id == merchant_id
                )
            ).all()
        )


def viable_workshop_body(
    *,
    title: str = "Pottery Workshop",
    ticket_price_minor: int = 5000,
    capacity: int = 8,
    fixed_costs_minor: int = 12000,
) -> dict:
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    return {
        "title": title,
        "description": "Hands-on throwing",
        "financials": {
            "currency": "GBP",
            "ticket_price_minor": ticket_price_minor,
            "capacity": capacity,
            "minimum_operating_attendance": 4,
            "fixed_costs_minor": fixed_costs_minor,
            "shipping_allowance_minor": 0,
            "contingency_minor": 500,
            "fee_estimate": {
                "percent_basis_points": 249,
                "fixed_minor": 30,
                "label": "merchant-entered-conservative-estimate",
            },
            "materials": [
                {
                    "name": "Clay",
                    "source_label": "merchant-entered-assumption",
                    "kind": "consumable",
                    "shared_units": 0,
                    "per_attendee_units": 1,
                    "pack_size": 4,
                    "pack_price_minor": 1600,
                }
            ],
        },
        "schedule": {
            "opens_at": (now + timedelta(hours=4)).isoformat(),
            "closes_at": (now + timedelta(hours=36)).isoformat(),
        },
    }