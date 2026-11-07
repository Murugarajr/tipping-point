"""Existing authentication owns settlement disclosure; no execution API is added."""

import asyncio
import uuid
from fastapi.testclient import TestClient
from sqlalchemy import select

from tipping_point.app import create_app
from tipping_point.auth.service import hash_token
from tipping_point.db.models import Booking, GuestSession, MerchantCredential, Workshop
from tipping_point.db.session import SessionLocal
from tipping_point.auth.passwords import hash_password
from tipping_point.guest.service import BookingService
from .api_helpers import login_client, logged_in_client
from .test_settlement import advance, settlement_case


def test_settlement_status_obeys_guest_and_merchant_ownership(settlement_case,owned):
    case=settlement_case(n=1)
    assert advance(case)=="CONFIRMED"
    app=create_app(case.settings)
    client=TestClient(app)
    with SessionLocal() as db:
        b=db.get(Booking,case.rows[0].id)
        guest=db.get(GuestSession,b.guest_session_id)
        guest.token_hash=hash_token("offline-owned-guest-cookie")
        guest.csrf_token_hash=hash_token("offline-owned-csrf")
        workshop=db.get(Workshop,case.workshop_id)
        db.add(MerchantCredential(merchant_id=workshop.merchant_id,login_identifier="settlement-"+uuid.uuid4().hex,
                                  password_hash=hash_password("offline-password")))
        db.commit()
        credential=db.scalar(select(MerchantCredential).where(MerchantCredential.merchant_id==workshop.merchant_id))
        login=credential.login_identifier
    assert client.get(f"/api/bookings/{b.id}").status_code==401
    client.cookies.set("tipping_guest_session","offline-owned-guest-cookie")
    response=client.get(f"/api/bookings/{b.id}")
    assert response.status_code==200
    data=response.json()
    assert data["workshop_confirmed"] and data["campaign_status"]=="CONFIRMED"
    assert data["captured_minor"]==1000 and not data["can_cancel"]
    assert not any(k in data for k in ("email","expected_payee","decision_id","provider_authorization_id"))
    assert client.get(f"/api/merchant/workshops/{case.workshop_id}").status_code==401
    assert login_client(client,login,"offline-password")[0]==200
    host=client.get(f"/api/merchant/workshops/{case.workshop_id}")
    assert host.status_code==200 and host.json()["campaign"]["settlement"]["collected_minor"]==1000
    other,_=logged_in_client(owned,app=app)
    assert other.get(f"/api/merchant/workshops/{case.workshop_id}").status_code==404
    for path in (f"/api/campaigns/{case.campaign_id}/settle",f"/api/campaigns/{case.campaign_id}/confirm"):
        assert TestClient(app).post(path,json={}).status_code in (404,405)
