"""Automatic deadline release through the Render Workflow path, offline.

Real PostgreSQL (tipping_point_test), MockTransport PayPal and a fake Render client that emulates the
documented task idempotency-key behaviour. No network call is made (the autouse fixture forbids it).

Scenario: one Sandbox-style campaign whose single authorized booking is below the minimum operating
attendance. At the deadline the dispatched task must release (void) that authorization and never capture.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select, update

from tipping_point.db.engine import engine
from tipping_point.db.models import Booking, Campaign, CampaignDecision, PaymentOperation, SettlementWork
from tipping_point.db.session import SessionLocal
from tipping_point.guest.service import BookingService, utcnow
from tipping_point.settings import AppSettings
from tipping_point.settlement.decision import enqueue
from tipping_point.settlement.projections import campaign_projection, guest_projection
from tipping_point.workflows.dispatcher import dispatch_due
from tipping_point.workflows.tasks import settle_campaign_pass
from .test_render_workflow import configured, fake_client, posts, refusing_session, status, with_due_work, work
from .test_settlement import settlement_case  # noqa: F401


def run(case, campaign_id, settings, render_run_id=None):
    @contextmanager
    def bound_session():
        with engine.connect() as connection, SessionLocal(bind=connection) as db:
            case.provider.local.db = db
            yield db
    return asyncio.run(settle_campaign_pass(
        campaign_id, settings=settings, session_factory=bound_session,
        gateway_factory=lambda _settings: case.gateway, render_run_id=render_run_id))


def below_threshold(settlement_case):
    # One authorized booking; the frozen terms need at least two attendees.
    return settlement_case(n=1, price=100, minimum=2)


def decisions(case):
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(CampaignDecision).where(CampaignDecision.campaign_id == case.campaign_id))


def operations(case, kind=None):
    with SessionLocal() as db:
        query = select(PaymentOperation.kind, PaymentOperation.state).join(Booking).where(Booking.campaign_id == case.campaign_id)
        if kind:
            query = query.where(PaymentOperation.kind == kind)
        return [tuple(row) for row in db.execute(query)]


def views(case):
    """What the merchant console/Intelligence and the guest booking page are served."""
    with SessionLocal() as db:
        campaign = db.get(Campaign, case.campaign_id)
        booking = db.get(Booking, case.rows[0].id)
        guest = BookingService(db, case.settings).booking_out(booking)
        return campaign_projection(db, campaign), guest, guest_projection(db, booking, campaign)


def drain(case, client, settings, *, start, limit=4):
    """Later dispatcher ticks: execute each newly submitted run until no work is eligible."""
    for tick in range(1, limit + 1):
        summary = dispatch_due(client, settings, now=start + timedelta(minutes=2 * tick))
        if summary["eligible"] == 0:
            return tick
        for item in summary["runs"]:
            run(case, item["campaign_id"], settings, render_run_id=item["run_id"])
    raise AssertionError("work never drained")


# ---- before cutoff ------------------------------------------------------------------------------------

def test_nothing_is_dispatched_or_executed_before_cutoff(settlement_case):
    case = below_threshold(settlement_case)
    later = utcnow() + timedelta(hours=1)
    with SessionLocal() as db:
        db.execute(update(Campaign).where(Campaign.id == case.campaign_id).values(cutoff_at=later))
        campaign = db.get(Campaign, case.campaign_id)
        enqueue(db, campaign, purpose="DEADLINE", due_at=later)  # as publication arms it
        db.commit()
    settings = configured(case)
    client = fake_client()
    assert dispatch_due(client, settings)["eligible"] == 0 and client.workflows.calls == []

    # A forged/premature run (even with due work present) is stopped by the worker's own cutoff check.
    with SessionLocal() as db:
        db.execute(update(SettlementWork).where(SettlementWork.campaign_id == case.campaign_id).values(due_at=utcnow() - timedelta(minutes=1)))
        db.commit()
    result = run(case, str(case.campaign_id), settings)
    assert result["financial_execution"] == "permitted" and result["pass_errors"] == ["HTTPException"]
    assert decisions(case) == 0 and status(case) == "OPEN" and case.provider.calls == []
    assert result["persisted_state"]["decision"] is None


# ---- allowlist ----------------------------------------------------------------------------------------

def test_exact_allowlist_only_empty_or_widened_settings_process_nothing(settlement_case):
    target, other = below_threshold(settlement_case), below_threshold(settlement_case)
    with_due_work(target), with_due_work(other)

    # No "all campaigns" mode exists any more, and an empty allowlist cannot start.
    with pytest.raises(ValidationError):
        AppSettings(_env_file=None, allow_insecure_dev_cookies=True, remote_settlement_mode="enabled")
    with pytest.raises(RuntimeError, match="at least one campaign"):
        AppSettings(_env_file=None, allow_insecure_dev_cookies=True, remote_settlement_mode="campaign_allowlist").validate_startup()

    # Even if startup validation were bypassed, an empty allowlist permits nothing in either service.
    empty = configured(target, campaigns=[])
    client = fake_client()
    assert dispatch_due(client, empty, session_factory=refusing_session)["eligible"] == 0 and client.workflows.calls == []
    refused = asyncio.run(settle_campaign_pass(str(target.campaign_id), settings=empty, session_factory=refusing_session))
    assert refused["financial_execution"] == "refused" and refused["reason"] == "CAMPAIGN_NOT_ALLOWLISTED"

    # Allowlisting one campaign dispatches only that one.
    settings = configured(target)
    summary = dispatch_due(client, settings)
    assert [r["campaign_id"] for r in summary["runs"]] == [str(target.campaign_id)]
    assert all(call["input"] == {"campaign_id": str(target.campaign_id)} for call in client.workflows.calls)

    # A forged direct run for the other, due campaign is refused by the workflow itself, before any DB access.
    forged = asyncio.run(settle_campaign_pass(str(other.campaign_id), settings=settings, session_factory=refusing_session,
                                              render_run_id="trn-forged"))
    assert forged["reason"] == "CAMPAIGN_NOT_ALLOWLISTED" and forged["render_task_run_id"] == "trn-forged"
    untouched = work(other)
    assert (status(other), untouched.state, untouched.version, untouched.attempts) == ("OPEN", "READY", 0, 0)
    assert decisions(other) == 0 and other.provider.calls == []


# ---- the milestone: automatic below-threshold release -------------------------------------------------

def test_below_threshold_deadline_releases_once_without_capture_under_duplicate_delivery(settlement_case):
    case = below_threshold(settlement_case)
    with_due_work(case)
    settings = configured(case)
    client = fake_client()
    start = utcnow()
    summary = dispatch_due(client, settings, now=start)
    assert summary["submitted"] == 1
    submitted = summary["runs"][0]
    task_run = next(iter(client.workflows.runs.values()))
    assert submitted["run_id"] == task_run.id

    # The same run delivered twice concurrently on separate sessions.
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: run(case, task_run.input["campaign_id"], settings, render_run_id=task_run.id), range(2)))
    claimed = [r for r in results if r["claimed"]]
    assert len(claimed) == 1
    first = claimed[0]["persisted_state"]
    assert first["campaign"] == "CANCELLED"
    assert first["decision"]["result"] == "RELEASE" and first["decision"]["reason"] == "ACTUAL_ATTENDANCE_NOT_VIABLE"
    assert first["decision"]["cohort_booking_ids"] == [str(case.rows[0].id)]
    assert claimed[0]["render_task_run_id"] == task_run.id
    assert {(op["kind"], op["state"]) for op in first["payment_operations"]} >= {("VOID", "SUCCEEDED")}

    # Remaining ticks close the work row; late duplicates never mutate again.
    drain(case, client, settings, start=start)
    assert run(case, str(case.campaign_id), settings)["claimed"] is False
    assert len(posts(case, "/void")) == 1 and posts(case, "/capture") == []
    assert operations(case, "VOID") == [("VOID", "SUCCEEDED")] and operations(case, "CAPTURE") == []
    assert decisions(case) == 1, "exactly one frozen deadline decision"
    assert work(case).state == "DONE"

    merchant, guest, guest_money = views(case)
    assert (merchant["state"], merchant["decision_result"], merchant["frozen_attendance"]) == ("CANCELLED", "RELEASE", 1)
    assert (merchant["collected_minor"], merchant["authorized_minor"], merchant["release_pending"], merchant["review_required"]) == (0, 0, 0, False)
    assert guest.state == "VOIDED" and guest_money["captured_minor"] == 0 and guest_money["campaign_status"] == "CANCELLED"


def test_unknown_void_is_not_shown_as_released_and_reconciles_by_retrieval_only(settlement_case):
    case = below_threshold(settlement_case)
    case.provider.timeout_void.add(case.rows[0].id)  # PayPal voids, the response is lost
    with_due_work(case)
    settings = configured(case)
    client = fake_client()
    start = utcnow()
    summary = dispatch_due(client, settings, now=start)
    first = run(case, summary["runs"][0]["campaign_id"], settings, render_run_id=summary["runs"][0]["run_id"])

    assert first["claimed"] is True and first["persisted_state"]["campaign"] == "RELEASING"
    assert operations(case, "VOID") == [("VOID", "UNKNOWN")]
    merchant, guest, _ = views(case)
    assert merchant["state"] == "RELEASING" and merchant["release_pending"] == 1 and merchant["review_required"] is True
    assert merchant["authorized_minor"] == 100, "an unconfirmed release still counts as authorized"
    assert guest.state != "VOIDED"
    assert work(case).state == "READY", "unresolved work stays due for the next dispatch"

    # Next dispatcher ticks: retrieval finds the authorization VOIDED; no second void POST.
    drain(case, client, settings, start=start)
    assert len(posts(case, "/void")) == 1 and posts(case, "/capture") == []
    assert operations(case, "VOID") == [("VOID", "SUCCEEDED")]
    merchant, guest, _ = views(case)
    assert (merchant["state"], merchant["release_pending"], merchant["review_required"]) == ("CANCELLED", 0, False)
    assert guest.state == "VOIDED" and decisions(case) == 1


def test_overdue_campaigns_outside_the_allowlist_are_never_discovered_or_frozen(settlement_case):
    """A backlog of overdue OPEN campaigns stays untouched while one exact campaign is processed."""
    target, backlog = below_threshold(settlement_case), below_threshold(settlement_case)
    with_due_work(target)  # only the target has been armed; the backlog campaign has no work row at all
    settings = configured(target)
    client = fake_client()
    summary = dispatch_due(client, settings)
    run(case=target, campaign_id=summary["runs"][0]["campaign_id"], settings=settings)
    with SessionLocal() as db:
        assert db.scalar(select(SettlementWork.id).where(SettlementWork.campaign_id == backlog.campaign_id)) is None
    assert status(backlog) == "OPEN" and decisions(backlog) == 0 and backlog.provider.calls == []
    assert status(target) == "CANCELLED"


def test_campaign_id_is_never_trusted_for_a_different_campaign(settlement_case):
    case = below_threshold(settlement_case)
    with_due_work(case)
    result = run(case, str(uuid.uuid4()), configured(case, campaigns=[case.campaign_id]))
    assert result["financial_execution"] == "refused" and status(case) == "OPEN" and case.provider.calls == []
