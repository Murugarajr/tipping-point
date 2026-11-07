"""Independent PostgreSQL connections and explicit provider/lock synchronization."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import threading
import uuid

from sqlalchemy import event, select, text
from sqlalchemy.exc import DBAPIError
import pytest

from tipping_point.db.engine import engine
from tipping_point.db.models import (
    Booking, Campaign, CampaignDecision, DecisionCohortMember, PaymentOperation, SettlementWork,
)
from tipping_point.db.session import SessionLocal
from tipping_point.guest.payments import BookingPaymentService, OperationClaim
from tipping_point.guest.service import utcnow
from tipping_point.paypal.client import parse_order
from tipping_point.settlement.decision import enqueue, freeze_decision
from tipping_point.settlement.dispatch import claim_due, discover_due, finish_work
from tipping_point.settlement.service import SettlementService
from .test_settlement import advance, settlement_case, state


def test_duplicate_deadline_delivery_uses_one_frozen_decision(settlement_case):
    case=settlement_case(n=1)
    barrier=threading.Barrier(2)
    connections=set()
    lock=threading.Lock()
    def decide():
        with engine.connect() as connection, SessionLocal(bind=connection) as db:
            pid=db.scalar(text("SELECT pg_backend_pid()"));db.commit()
            with lock: connections.add(pid)
            barrier.wait(timeout=10)
            return freeze_decision(db,case.campaign_id,case.settings).id
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids=list(pool.map(lambda _:decide(),range(2)))
    assert len(connections)==2 and ids[0]==ids[1]
    with SessionLocal() as db:
        assert len(list(db.scalars(select(CampaignDecision).where(CampaignDecision.campaign_id==case.campaign_id))))==1
        assert len(list(db.scalars(select(DecisionCohortMember).where(DecisionCohortMember.decision_id==ids[0]))))==1


def test_late_authorization_cannot_join_frozen_cohort_and_is_released(settlement_case):
    case=settlement_case(n=1)
    b=case.rows[0]
    with SessionLocal() as db:
        booking=db.get(Booking,b.id)
        booking.state="AUTHORIZATION_PENDING";booking.admitted_at=None
        booking.reservation_expires_at=utcnow()+timedelta(minutes=5)
        operation=db.scalar(select(PaymentOperation).where(PaymentOperation.booking_id==b.id,PaymentOperation.kind=="AUTHORIZE"))
        operation.state="IN_FLIGHT";operation.claim_token=uuid.uuid4();operation.version=1
        operation.lease_expires_at=utcnow()+timedelta(minutes=2)
        db.commit()
        claim=OperationClaim(operation.id,b.id,operation.claim_token,operation.version,str(operation.request_id),
                             "AUTHORIZE",operation.resource_scope,dict(operation.request_payload))
    arrived,release=threading.Event(),threading.Event()
    def pause(_):
        arrived.set()
        assert release.wait(timeout=15)
    case.provider.before_authorization_read=pause
    pids=set()
    def admit():
        with engine.connect() as connection, SessionLocal(bind=connection) as db:
            pids.add(db.scalar(text("SELECT pg_backend_pid()")));db.commit()
            case.provider.local.db=db
            asyncio.run(BookingPaymentService(db,case.settings,case.gateway)._inspect_authorizations(
                claim,parse_order(case.provider.order(b))))
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(admit)
        try:
            assert arrived.wait(timeout=10)
            with SessionLocal() as db:
                pids.add(db.scalar(text("SELECT pg_backend_pid()")))
                decision=freeze_decision(db,case.campaign_id,case.settings)
                assert decision.attendance==0
        finally:
            release.set()
        future.result(timeout=20)
    assert len(pids)==2
    case.provider.before_authorization_read=None
    with SessionLocal() as db:
        assert db.get(Booking,b.id).admitted_at is None
        assert db.get(Booking,b.id).state=="RELEASE_PENDING"
        assert not list(db.scalars(select(DecisionCohortMember).where(DecisionCohortMember.booking_id==b.id)))
    assert advance(case)=="CANCELLED" and b.id in case.provider.voided


def test_cancellation_during_capture_refunds_late_success_and_stops_further_captures(settlement_case):
    case=settlement_case(n=2)
    arrived,release=threading.Event(),threading.Event()
    pids=set()
    def pause(_):
        arrived.set()
        assert release.wait(timeout=15)
    case.provider.before_capture=pause
    def collect():
        with engine.connect() as connection, SessionLocal(bind=connection) as db:
            pids.add(db.scalar(text("SELECT pg_backend_pid()")));db.commit()
            case.provider.local.db=db
            freeze_decision(db,case.campaign_id,case.settings)
            return asyncio.run(SettlementService(db,case.settings,case.gateway).advance(case.campaign_id))
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(collect)
        try:
            assert arrived.wait(timeout=10)
            with SessionLocal() as db:
                pids.add(db.scalar(text("SELECT pg_backend_pid()")));db.commit()
                asyncio.run(BookingPaymentService(db,case.settings,None).cancel(case.rows[0].id))
                assert db.get(Campaign,case.campaign_id).status=="ABORTING"
        finally:
            release.set()
        assert future.result(timeout=25)=="CANCELLED"
    assert len(pids)==2
    assert case.provider.refunds=={case.rows[0].id:"COMPLETED"}
    assert case.provider.voided=={case.rows[1].id}
    assert len([c for c in case.provider.calls if c[1].endswith("/capture")])==1


def test_duplicate_capture_workers_do_not_dispatch_duplicate_posts(settlement_case):
    case=settlement_case(n=1)
    arrived,release=threading.Event(),threading.Event()
    def pause(_):
        arrived.set()
        assert release.wait(timeout=15)
    case.provider.before_capture=pause
    def collect():
        return advance(case)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(collect)
        try:
            assert arrived.wait(timeout=10)
            second=pool.submit(collect)
            assert second.result(timeout=10)=="SETTLING"
        finally:
            release.set()
        assert first.result(timeout=20)=="CONFIRMED"
    assert len([c for c in case.provider.calls if c[1].endswith("/capture")])==1


def test_durable_work_wakeup_and_expired_lease_fence_stale_completion(settlement_case):
    case=settlement_case(n=1)
    with SessionLocal() as db:
        discover_due(db,campaign_id=case.campaign_id)
        first=claim_due(db,campaign_id=case.campaign_id)
        assert first is not None
    with SessionLocal() as db:
        assert claim_due(db,campaign_id=case.campaign_id) is None
        campaign=db.scalar(select(Campaign).where(Campaign.id==case.campaign_id).with_for_update())
        enqueue(db,campaign)
        db.commit()
        assert finish_work(db,first,terminal=True) is False
        work=db.get(SettlementWork,first.id)
        assert work.state=="READY"
        second=claim_due(db,campaign_id=case.campaign_id)
        work=db.get(SettlementWork,first.id)
        work.lease_expires_at=utcnow()-timedelta(seconds=1);db.commit()
    with SessionLocal() as db:
        third=claim_due(db,campaign_id=case.campaign_id)
        assert third is not None and third.token!=second.token
        assert finish_work(db,second,terminal=True) is False
        assert db.get(SettlementWork,first.id).claim_token==third.token


def test_concurrent_compensation_workers_do_not_dispatch_duplicate_refunds(settlement_case):
    case=settlement_case(n=2)
    case.provider.fail_capture.add(case.rows[1].id)
    arrived,release=threading.Event(),threading.Event()
    def pause(_):
        arrived.set()
        assert release.wait(timeout=15)
    case.provider.before_refund=pause
    # advance() pins a physical connection for each independent worker/session.
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(advance,case)
        try:
            assert arrived.wait(timeout=10)
            second=pool.submit(advance,case)
            assert second.result(timeout=10)=="COMPENSATING"
        finally:
            release.set()
        assert first.result(timeout=20)=="CANCELLED"
    assert len([c for c in case.provider.calls if c[1].endswith("/refund")])==1
    assert case.provider.refunds=={case.rows[0].id:"COMPLETED"}


def test_decision_and_cohort_expectations_cannot_be_rewritten(settlement_case):
    case=settlement_case(n=1)
    with SessionLocal() as db:
        decision=freeze_decision(db,case.campaign_id,case.settings)
        decision_id=decision.id
    with SessionLocal() as db:
        decision=db.get(CampaignDecision,decision_id);decision.attendance=999
        with pytest.raises(DBAPIError):db.commit()
        db.rollback()
        member=db.scalar(select(DecisionCohortMember).where(DecisionCohortMember.decision_id==decision_id))
        member.amount_minor=1
        with pytest.raises(DBAPIError):db.commit()
        db.rollback()


def test_cannot_force_a_decision_before_cutoff(settlement_case):
    from fastapi import HTTPException
    case=settlement_case(n=1)
    with SessionLocal() as db:
        # Campaign is test-owned; frozen published terms remain untouched.
        db.get(Campaign,case.campaign_id).cutoff_at=utcnow()+timedelta(hours=1);db.commit()
        with pytest.raises(HTTPException) as error:
            freeze_decision(db,case.campaign_id,case.settings)
        assert error.value.status_code==409
        db.rollback()
