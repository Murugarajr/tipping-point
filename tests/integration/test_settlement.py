"""Real PostgreSQL persistence; provider traffic is exclusively MockTransport."""

import asyncio
from datetime import timedelta
import json
from types import SimpleNamespace
import uuid

import httpx
import pytest
from sqlalchemy import select

from tipping_point.db.models import (
    Booking, Campaign, CampaignDecision, CampaignTerms, DecisionCohortMember,
    GuestSession, Merchant, PaymentOperation, Workshop,
)
from tipping_point.db.session import SessionLocal
from tipping_point.db.engine import engine
from tipping_point.economics import CampaignFinancialsInput, build_snapshot_hash, calculate_viability
from tipping_point.economics.calculator import ALGORITHM_VERSION
from tipping_point.guest.service import payload_hash, utcnow
from tipping_point.paypal.client import PayPalGateway, build_authorization_order_payload
from tipping_point.settings import AppSettings
from tipping_point.settlement.decision import freeze_decision
from tipping_point.settlement.projections import campaign_projection
from tipping_point.settlement.service import SettlementService


class SimulatedWorkerDeath(BaseException):
    pass


class Provider:
    def __init__(self, case):
        self.case = case
        self.captures, self.refunds, self.voided = {}, {}, set()
        self.fail_capture, self.pending_capture = set(), set()
        self.declined_capture = set()
        self.pending_refund, self.failed_refund = set(), set()
        self.timeout_capture, self.crash_capture = set(), set()
        self.malformed_capture = set()
        self.timeout_refund = set()
        self.calls, self.fees = [], {}
        self.before_capture = None
        self.before_refund = None
        self.before_authorization_read = None
        import threading
        self.local = threading.local()

    def row(self, resource):
        return next(b for b in self.case.rows if resource in (b.order_id, b.auth_id, b.capture_id, b.refund_id))

    def money(self):
        return {"currency_code": "GBP", "value": f"{self.case.price // 100}.{self.case.price % 100:02}"}

    def order(self, b):
        payments = {"authorizations": [{"id": b.auth_id, "status": "CREATED", "amount": self.money()}]}
        if b.id in self.captures:
            payments["captures"] = [{"id": b.capture_id, "status": self.captures[b.id], "amount": self.money()}]
        return {"id": b.order_id, "status": "COMPLETED", "intent": "AUTHORIZE", "purchase_units": [{
            "reference_id": str(b.id), "amount": self.money(), "payee": {"merchant_id": "OFFLINEPAYEE"},
            "payments": payments,
        }]}

    def capture(self, b):
        result = {"id": b.capture_id, "status": self.captures[b.id], "amount": self.money(),
                  "supplementary_data": {"related_ids": {"order_id": b.order_id, "authorization_id": b.auth_id}}}
        if b.id in self.fees:
            fee = self.fees[b.id]
            result["seller_receivable_breakdown"] = {"paypal_fee": {"currency_code": "GBP", "value": f"{fee // 100}.{fee % 100:02}"}}
        return result

    def refund(self, b):
        return {"id": b.refund_id, "status": self.refunds[b.id], "amount": self.money(),
                "links": [{"rel": "up", "href": f"https://api-m.sandbox.paypal.com/v2/payments/captures/{b.capture_id}", "method": "GET"}]}

    def __call__(self, request):
        db = getattr(self.local, "db", None)
        if db is not None:
            assert not db.in_transaction(), "Provider I/O occurred inside a transaction"
        path = request.url.path
        self.calls.append((request.method, path, request.headers.get("PayPal-Request-Id")))
        assert request.url.host == "api-m.sandbox.paypal.com"
        if path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "offline-only", "expires_in": 3600})
        resource = path.split("/")[-2] if path.endswith(("/capture", "/refund", "/void")) else path.split("/")[-1]
        b = self.row(resource)
        if request.method == "POST":
            # NOWAIT on a second connection proves locks were released before mutation.
            with SessionLocal() as observer:
                observer.execute(select(Campaign).where(Campaign.id == self.case.campaign_id).with_for_update(nowait=True))
                observer.execute(select(Booking).where(Booking.id == b.id).with_for_update(nowait=True))
            assert request.headers.get("PayPal-Request-Id")
        if path.endswith("/capture"):
            if self.before_capture:
                self.before_capture(b)
            assert json.loads(request.content) == {"amount": self.money(), "final_capture": True}
            if b.id in self.fail_capture:
                return httpx.Response(422, json={"details": [{"issue": "AUTHORIZATION_DENIED"}]})
            assert b.id not in self.captures, "Duplicate capture mutation"
            self.captures[b.id] = "PENDING" if b.id in self.pending_capture else "DECLINED" if b.id in self.declined_capture else "COMPLETED"
            if b.id in self.crash_capture:
                raise SimulatedWorkerDeath()
            if b.id in self.timeout_capture:
                self.timeout_capture.remove(b.id)
                raise httpx.ReadTimeout("offline lost response", request=request)
            if b.id in self.malformed_capture:
                self.malformed_capture.remove(b.id)
                return httpx.Response(201,json={**self.capture(b),"amount":{"currency_code":"GBP","value":"bad"}})
            return httpx.Response(201, json=self.capture(b))
        if path.endswith("/refund"):
            if self.before_refund:
                self.before_refund(b)
            assert json.loads(request.content) == {"amount": self.money()}
            assert b.id not in self.refunds, "Duplicate refund mutation"
            self.refunds[b.id] = "PENDING" if b.id in self.pending_refund else "FAILED" if b.id in self.failed_refund else "COMPLETED"
            if b.id in self.timeout_refund:
                raise httpx.ReadTimeout("offline unknown refund", request=request)
            return httpx.Response(201, json=self.refund(b))
        if path.endswith("/void"):
            assert self.captures.get(b.id) not in ("COMPLETED", "PENDING"), "Cannot void a captured payment"
            self.voided.add(b.id)
            return httpx.Response(204)
        if "/checkout/orders/" in path:
            return httpx.Response(200, json=self.order(b))
        if "/authorizations/" in path:
            if self.before_authorization_read:
                self.before_authorization_read(b)
            return httpx.Response(200, json={
                "id": b.auth_id, "status": "VOIDED" if b.id in self.voided else "CREATED",
                "amount": self.money(), "supplementary_data": {"related_ids": {"order_id": b.order_id}},
                "create_time": self.case.created.isoformat(),
                "expiration_time": (self.case.created + timedelta(days=29)).isoformat(),
            })
        if "/captures/" in path:
            return httpx.Response(200, json=self.capture(b))
        if "/refunds/" in path:
            return httpx.Response(200, json=self.refund(b))
        raise AssertionError("Unexpected fixture provider endpoint")


@pytest.fixture
def settlement_case(owned):
    gateways = []

    def make(n=2, *, price=1000, capacity=4, fixed=0, materials=None, minimum=1, fees=0):
        now = utcnow()
        merchant_id, workshop_id, terms_id, campaign_id = [uuid.uuid4() for _ in range(4)]
        owned.add(Merchant, merchant_id)
        inputs = CampaignFinancialsInput(
            ticket_price_minor=price, capacity=capacity, minimum_operating_attendance=minimum,
            fixed_costs_minor=fixed, materials=materials or [],
            fee_estimate={"percent_basis_points": 0, "fixed_minor": fees, "label": "offline reviewed assumption"},
        )
        opens, closes = now - timedelta(hours=1), now - timedelta(minutes=1)
        rows = [SimpleNamespace(id=i, order_id="ORDER"+i.hex, auth_id="AUTH"+i.hex,
                                capture_id="CAPTURE"+i.hex, refund_id="REFUND"+i.hex)
                for i in sorted([uuid.uuid4() for _ in range(n)])]
        with SessionLocal() as db:
            db.add(Merchant(id=merchant_id, name="Settlement offline "+uuid.uuid4().hex))
            db.flush()
            db.add(Workshop(id=workshop_id, merchant_id=merchant_id, title="Offline settlement",
                            capacity=capacity, ticket_price_minor=price, currency="GBP"))
            db.flush()
            db.add(CampaignTerms(id=terms_id, workshop_id=workshop_id, version=1, currency="GBP",
                financial_inputs=inputs.model_dump(mode="json"), assumption_labels={}, calculation={},
                algorithm_version=ALGORITHM_VERSION, snapshot_hash=build_snapshot_hash(inputs, opens_at=opens, closes_at=closes),
                opens_at=opens, closes_at=closes, is_frozen=True, frozen_at=opens))
            db.flush()
            db.add(Campaign(id=campaign_id, workshop_id=workshop_id, terms_id=terms_id, terms_version=1,
                            status="OPEN", capacity=capacity, cutoff_at=closes))
            db.flush()
            for b in rows:
                guest_id = uuid.uuid4()
                owned.add(GuestSession, guest_id)
                db.add(GuestSession(id=guest_id, token_hash=uuid.uuid4().hex, csrf_token_hash=uuid.uuid4().hex,
                                    expires_at=now+timedelta(days=1)))
                db.flush()
                db.add(Booking(id=b.id, campaign_id=campaign_id, guest_session_id=guest_id, terms_id=terms_id,
                    idempotency_key=uuid.uuid4(), reservation_payload_hash="0"*64, email="offline@example.test",
                    amount_minor=price, currency="GBP", expected_payee="OFFLINEPAYEE",
                    return_url=f"http://localhost:5173/bookings/{b.id}/paypal/return",
                    cancel_url=f"http://localhost:5173/bookings/{b.id}/paypal/cancel",
                    provider_order_id=b.order_id, provider_authorization_id=b.auth_id,
                    state="AUTHORIZED", admitted_at=now-timedelta(minutes=2),
                    reservation_expires_at=now-timedelta(seconds=1), created_at=now-timedelta(minutes=10),
                    authorization_created_at=now-timedelta(minutes=5), authorization_expires_at=now+timedelta(days=29)))
                db.flush()
                create_payload=build_authorization_order_payload(reference_id=str(b.id),amount_minor=price,currency="GBP",
                    expected_payee="OFFLINEPAYEE", return_url=f"http://localhost:5173/bookings/{b.id}/paypal/return",
                    cancel_url=f"http://localhost:5173/bookings/{b.id}/paypal/cancel")
                for kind,scope,payload in [("CREATE_ORDER","",create_payload),("AUTHORIZE",b.order_id,{"order_id":b.order_id,"body":{}})]:
                    db.add(PaymentOperation(booking_id=b.id,kind=kind,resource_scope=scope,request_payload=payload,
                        request_hash=payload_hash(payload),state="SUCCEEDED",provider_resource_id=b.order_id))
            db.commit()
        case=SimpleNamespace(campaign_id=campaign_id,workshop_id=workshop_id,terms_id=terms_id,rows=rows,price=price,
                             inputs=inputs,created=now-timedelta(minutes=5))
        case.settings=AppSettings(_env_file=None,allow_insecure_dev_cookies=True,paypal_client_id="offline",
            paypal_client_secret="offline",paypal_expected_payee="OFFLINEPAYEE",public_url="http://localhost:5173")
        case.provider=Provider(case)
        case.gateway=PayPalGateway.from_settings(case.settings,transport=httpx.MockTransport(case.provider))
        gateways.append(case.gateway)
        return case
    yield make
    for gateway in gateways:
        asyncio.run(gateway.aclose())


def advance(case):
    with engine.connect() as connection, SessionLocal(bind=connection) as db:
        case.provider.local.db=db
        freeze_decision(db,case.campaign_id,case.settings)
        return asyncio.run(SettlementService(db,case.settings,case.gateway).advance(case.campaign_id))


def state(case):
    with SessionLocal() as db:
        c=db.get(Campaign,case.campaign_id)
        return campaign_projection(db,c)


def test_below_threshold_releases_without_capturing(settlement_case):
    case=settlement_case(n=2,minimum=3)
    assert advance(case)=="CANCELLED"
    assert len(case.provider.voided)==2 and not case.provider.captures
    assert state(case)["decision_result"]=="RELEASE"


def test_attendance_above_first_viable_can_still_be_nonviable(settlement_case):
    case=settlement_case(n=3,price=200,materials=[{
        "name":"Pack jump","source_label":"offline assumption","shared_units":0,
        "per_attendee_units":1,"pack_size":2,"pack_price_minor":350,
    }])
    assert calculate_viability(case.inputs).first_viable_attendance==2
    assert advance(case)=="CANCELLED" and not case.provider.captures
    assert state(case)["frozen_attendance"]==3


def test_complete_collection_confirms_and_duplicate_pass_does_not_capture_again(settlement_case):
    case=settlement_case()
    assert advance(case)=="CONFIRMED"
    assert advance(case)=="CONFIRMED"
    assert len(case.provider.captures)==2
    assert state(case)["collected_minor"]==2000 and not state(case)["review_required"]


def test_pending_capture_blocks_confirmation_and_later_completes(settlement_case):
    case=settlement_case()
    case.provider.pending_capture.add(case.rows[0].id)
    assert advance(case)=="SETTLING"
    assert state(case)["collected_minor"]==0 and len(case.provider.captures)==1
    case.provider.captures[case.rows[0].id]="COMPLETED"
    assert advance(case)=="CONFIRMED"
    assert len([c for c in case.provider.calls if c[1].endswith("/capture")])==2


def test_failure_after_success_refunds_and_releases_remaining(settlement_case):
    case=settlement_case(n=3)
    case.provider.fail_capture.add(case.rows[1].id)
    assert advance(case)=="CANCELLED"
    assert case.provider.refunds=={case.rows[0].id:"COMPLETED"}
    assert case.provider.voided=={case.rows[1].id,case.rows[2].id}
    assert len([c for c in case.provider.calls if c[1].endswith("/capture")])==2


@pytest.mark.parametrize("failed",[False,True])
def test_pending_or_failed_refund_is_visible_not_cancelled(settlement_case,failed):
    case=settlement_case()
    case.provider.fail_capture.add(case.rows[1].id)
    (case.provider.failed_refund if failed else case.provider.pending_refund).add(case.rows[0].id)
    assert advance(case)=="COMPENSATING"
    projection=state(case)
    assert projection["refund_pending"]==1 and projection["refunded_minor"]==0
    if failed:
        assert projection["review_required"]
    else:
        case.provider.refunds[case.rows[0].id]="COMPLETED"
        assert advance(case)=="CANCELLED"
    assert len([c for c in case.provider.calls if c[1].endswith("/refund")])==1


def test_unknown_capture_is_retrieved_without_replacement_mutation(settlement_case):
    case=settlement_case(n=1)
    case.provider.timeout_capture.add(case.rows[0].id)
    assert advance(case)=="SETTLING"
    assert advance(case)=="CONFIRMED"
    assert len([c for c in case.provider.calls if c[1].endswith("/capture")])==1
    with SessionLocal() as db:
        assert len(list(db.scalars(select(PaymentOperation).where(
            PaymentOperation.booking_id==case.rows[0].id,PaymentOperation.kind=="CAPTURE"))))==1


def test_restart_after_provider_success_before_local_persistence(settlement_case):
    case=settlement_case(n=1)
    case.provider.crash_capture.add(case.rows[0].id)
    with pytest.raises(SimulatedWorkerDeath):
        advance(case)
    with SessionLocal() as db:
        operation=db.scalar(select(PaymentOperation).where(
            PaymentOperation.booking_id==case.rows[0].id,PaymentOperation.kind=="CAPTURE"))
        request_id=operation.request_id
        operation.lease_expires_at=utcnow()-timedelta(seconds=1)
        operation.created_at=utcnow()-timedelta(days=100)  # beyond any assumed replay window
        db.commit()
    assert advance(case)=="CONFIRMED"
    captures=[c for c in case.provider.calls if c[1].endswith("/capture")]
    assert len(captures)==1 and captures[0][2]==str(request_id)


def test_unknown_refund_without_reference_escalates_without_second_post(settlement_case):
    case=settlement_case()
    case.provider.fail_capture.add(case.rows[1].id)
    case.provider.timeout_refund.add(case.rows[0].id)
    assert advance(case)=="COMPENSATING"
    assert advance(case)=="COMPENSATING"
    assert state(case)["review_required"] and len([c for c in case.provider.calls if c[1].endswith("/refund")])==1


def test_actual_fees_can_abort_previously_viable_collection(settlement_case):
    case=settlement_case(n=1,fixed=950)
    case.provider.fees[case.rows[0].id]=100
    assert advance(case)=="CANCELLED"
    assert state(case)["post_collection_surplus_minor"]==-50
    assert case.provider.refunds[case.rows[0].id]=="COMPLETED"


def test_declined_capture_resource_is_not_paid_and_remaining_authorization_is_voided(settlement_case):
    case=settlement_case(n=1)
    case.provider.declined_capture.add(case.rows[0].id)
    assert advance(case)=="CANCELLED"
    assert case.rows[0].id in case.provider.voided and not case.provider.refunds
    assert state(case)["collected_minor"]==0


def test_pending_capture_late_success_after_policy_abort_is_refunded(settlement_case,monkeypatch):
    case=settlement_case(n=1)
    case.provider.pending_capture.add(case.rows[0].id)
    assert advance(case)=="SETTLING"
    from tipping_point.settlement import service
    monkeypatch.setattr(service,"utcnow",lambda:utcnow()+timedelta(hours=1))
    assert advance(case)=="COMPENSATING"
    assert not case.provider.voided and not case.provider.refunds
    case.provider.captures[case.rows[0].id]="COMPLETED"
    assert advance(case)=="CANCELLED"
    assert case.provider.refunds[case.rows[0].id]=="COMPLETED"
    assert len([c for c in case.provider.calls if c[1].endswith("/capture")])==1


def test_known_refund_recovery_only_retrieves_original_operation(settlement_case):
    case=settlement_case()
    case.provider.fail_capture.add(case.rows[1].id)
    case.provider.timeout_refund.add(case.rows[0].id)
    assert advance(case)=="COMPENSATING"
    with SessionLocal() as db:
        case.provider.local.db=db
        assert asyncio.run(SettlementService(db,case.settings,case.gateway).recover_reference(
            case.campaign_id,case.rows[0].id,"REFUND",case.rows[0].refund_id))
    assert advance(case)=="CANCELLED"
    assert len([c for c in case.provider.calls if c[1].endswith("/refund")])==1


def test_dispatcher_runs_durable_due_work_without_duplicate_capture(settlement_case):
    from tipping_point.settlement.dispatch import process_due
    case=settlement_case(n=1)
    with SessionLocal() as db:
        case.provider.local.db=db
        result=asyncio.run(process_due(db,case.settings,case.gateway,limit=3,campaign_id=case.campaign_id))
        assert result and result[-1]["state"]=="CONFIRMED"
        assert asyncio.run(process_due(db,case.settings,case.gateway,limit=3,campaign_id=case.campaign_id))==[]
    assert len([c for c in case.provider.calls if c[1].endswith("/capture")])==1


@pytest.mark.parametrize("kind",["CAPTURE","REFUND"])
def test_stale_success_is_observed_then_reconciled_without_another_mutation(settlement_case,kind):
    case=settlement_case(n=1 if kind=="CAPTURE" else 2)
    if kind=="REFUND":
        case.provider.fail_capture.add(case.rows[1].id)
    def stale(b):
        with SessionLocal() as db:
            operation=db.scalar(select(PaymentOperation).where(
                PaymentOperation.booking_id==b.id,PaymentOperation.kind==kind))
            operation.version+=1;operation.claim_token=uuid.uuid4()
            operation.state="UNKNOWN";operation.lease_expires_at=None
            db.commit()
    if kind=="CAPTURE":case.provider.before_capture=stale
    else:case.provider.before_refund=stale
    assert advance(case)==("SETTLING" if kind=="CAPTURE" else "COMPENSATING")
    assert advance(case)==("CONFIRMED" if kind=="CAPTURE" else "CANCELLED")
    suffix="/capture" if kind=="CAPTURE" else "/refund"
    assert len([c for c in case.provider.calls if c[1].endswith(suffix)
                and c[1].split("/")[-2] in (case.rows[0].auth_id,case.rows[0].capture_id)])==1


def test_bounded_capture_pass_resumes_after_already_completed_members(settlement_case):
    case=settlement_case()
    for expected in ("SETTLING","CONFIRMED"):
        with SessionLocal() as db:
            case.provider.local.db=db
            freeze_decision(db,case.campaign_id,case.settings)
            assert asyncio.run(SettlementService(db,case.settings,case.gateway).advance(
                case.campaign_id,max_steps=1))==expected
    assert len([c for c in case.provider.calls if c[1].endswith("/capture")])==2


def test_malformed_capture_keeps_known_reference_for_retrieval_only_recovery(settlement_case):
    case=settlement_case(n=1)
    case.provider.malformed_capture.add(case.rows[0].id)
    assert advance(case)=="SETTLING"
    with SessionLocal() as db:
        member=db.scalar(select(DecisionCohortMember).where(DecisionCohortMember.booking_id==case.rows[0].id))
        assert member.capture_id==case.rows[0].capture_id
    assert advance(case)=="CONFIRMED"
    assert len([c for c in case.provider.calls if c[1].endswith("/capture")])==1
