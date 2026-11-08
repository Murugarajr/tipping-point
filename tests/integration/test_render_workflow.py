"""Render Workflow adapter, offline: real PostgreSQL (tipping_point_test), MockTransport PayPal,
and a fake Render client that emulates documented task idempotency-key behaviour.

No Render, PayPal or Channel3 network call is made (the autouse fixture forbids external HTTP).
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import logging
from types import SimpleNamespace
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select

from tipping_point.app import create_app
from tipping_point.db.engine import engine
from tipping_point.db.models import Campaign, PaymentOperation, SettlementWork
from tipping_point.db.session import SessionLocal
from tipping_point.guest.service import utcnow
from tipping_point.paypal.client import PayPalGateway
from tipping_point.settlement.decision import CLEANUP_PURPOSE
from tipping_point.settlement.dispatch import discover_due
from tipping_point.workflows.dispatcher import BUCKET_SECONDS, dispatch_due, eligible_work
from tipping_point.workflows.tasks import TaskInputError, readiness_report, settle_campaign_pass
from .test_sandbox_cleanup import REASON, confirmed, req
from .test_settlement import SimulatedWorkerDeath, settlement_case  # noqa: F401

SLUG = "tipping-point-workflows"


class FakeRenderWorkflows:
    """Emulates documented start_task semantics: a reused idempotency key returns the original run."""

    def __init__(self):
        self.runs, self.calls, self.lose_responses = {}, [], 0

    def start_task(self, task_slug, input_data, *, idempotency_key=None):
        self.calls.append({"task": task_slug, "input": input_data, "key": idempotency_key})
        run = self.runs.get(idempotency_key)
        if run is None:
            run = SimpleNamespace(id=f"trn-{len(self.runs) + 1:04d}", status="pending", task=task_slug, input=dict(input_data))
            self.runs[idempotency_key] = run
        if self.lose_responses:
            self.lose_responses -= 1
            raise TimeoutError("response lost after the run was created")
        return run


def fake_client():
    return SimpleNamespace(workflows=FakeRenderWorkflows())


def configured(case, mode="campaign_allowlist", campaigns=None, **extra):
    ids = campaigns if campaigns is not None else [case.campaign_id]
    return case.settings.model_copy(update={
        "remote_settlement_mode": mode, "remote_settlement_campaign_ids": ",".join(str(c) for c in ids),
        "render_workflow_slug": SLUG, **extra})


def run_task(case, campaign_id, settings, gateway=None):
    """Execute the real task body as Render would, against the test DB and mock PayPal."""
    @contextmanager
    def bound_session():
        with engine.connect() as connection, SessionLocal(bind=connection) as db:
            case.provider.local.db = db
            yield db
    return asyncio.run(settle_campaign_pass(
        campaign_id, settings=settings, session_factory=bound_session,
        gateway_factory=lambda _settings: gateway or case.gateway))


def execute_run(case, run, settings):
    return run_task(case, run.input["campaign_id"], settings)


def with_due_work(case):
    with SessionLocal() as db:
        discover_due(db, campaign_id=case.campaign_id)  # as publication would have enqueued it
    return work(case)


def work(case):
    with SessionLocal() as db:
        w = db.scalar(select(SettlementWork).where(SettlementWork.campaign_id == case.campaign_id))
        return None if w is None else SimpleNamespace(**{k: getattr(w, k) for k in (
            "id", "purpose", "state", "version", "attempts", "claim_token", "due_at", "lease_expires_at")})


def status(case):
    with SessionLocal() as db:
        return db.get(Campaign, case.campaign_id).status


def posts(case, suffix):
    return [c for c in case.provider.calls if c[0] == "POST" and c[1].endswith(suffix)]


def refusing_session():
    raise AssertionError("the database must not be touched")


def test_task_inputs_resolve_only_permitted_persisted_campaigns(settlement_case):
    case = settlement_case(n=1, price=100)
    settings = configured(case)
    for bad in (None, 123, "not-a-uuid", str(case.campaign_id).upper(), "{" + str(case.campaign_id) + "}",
                {"campaign_id": str(case.campaign_id)}, [str(case.campaign_id)], str(case.campaign_id) + " "):
        with pytest.raises(TaskInputError) as error:
            asyncio.run(settle_campaign_pass(bad, settings=settings, session_factory=refusing_session))
        assert str(case.campaign_id) not in str(error.value).lower()  # input is never echoed
    # A well-formed but unlisted campaign is refused before any database access.
    other = str(uuid.uuid4())
    refused = asyncio.run(settle_campaign_pass(other, settings=settings, session_factory=refusing_session))
    assert refused["financial_execution"] == "refused" and refused["reason"] == "CAMPAIGN_NOT_ALLOWLISTED"
    # Enabled mode with a non-persisted campaign: nothing to claim, nothing sent to PayPal.
    unknown = run_task(case, other, configured(case, mode="enabled", campaigns=[]))
    assert unknown["claimed"] is False and unknown["persisted_state"] == {"campaign": None, "work": None}
    assert case.provider.calls == []


def test_financial_execution_is_disabled_by_default_in_task_and_dispatcher(settlement_case):
    case = settlement_case(n=1, price=100)
    with_due_work(case)
    settings = configured(case, mode="disabled", campaigns=[])
    assert case.settings.model_copy().remote_settlement_mode == "disabled"  # AppSettings default
    result = asyncio.run(settle_campaign_pass(str(case.campaign_id), settings=settings, session_factory=refusing_session))
    assert result["financial_execution"] == "refused" and result["reason"] == "REMOTE_SETTLEMENT_DISABLED"
    client = fake_client()
    summary = dispatch_due(client, settings, session_factory=refusing_session)
    assert summary == {"mode": "disabled", "eligible": 0, "submitted": 0, "failed": 0, "runs": []}
    assert client.workflows.calls == [] and case.provider.calls == []
    assert status(case) == "OPEN" and work(case).state == "READY" and work(case).version == 0


def test_dispatch_then_duplicate_delivery_confirms_with_exactly_one_capture(settlement_case):
    case = settlement_case(n=1, price=100)
    before = with_due_work(case)
    settings = configured(case)
    client = fake_client()
    summary = dispatch_due(client, settings)
    assert summary["submitted"] == 1 and summary["runs"][0]["campaign_id"] == str(case.campaign_id)
    call = client.workflows.calls[0]
    assert call["task"] == f"{SLUG}/settle_campaign" and call["input"] == {"campaign_id": str(case.campaign_id)}
    assert call["key"].startswith(f"tp-settle:{before.id}:v{before.version}:b")
    run = next(iter(client.workflows.runs.values()))

    # The same run delivered twice, concurrently, on separate sessions/threads.
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: execute_run(case, run, settings), range(2)))
    assert sorted(r["claimed"] for r in results) == [False, True]
    assert len(posts(case, "/capture")) == 1 and status(case) == "CONFIRMED"
    claimed = next(r for r in results if r["claimed"])
    assert claimed["persisted_state"]["campaign"] == "CONFIRMED" and claimed["financial_execution"] == "permitted"
    # Confirmation re-arms the row as PROGRESS (version bump), so one more bounded pass closes it.
    # That pass may be a late duplicate delivery: it only re-reads the capture, never POSTs again.
    follow_up = execute_run(case, run, settings)
    assert follow_up["claimed"] is True and follow_up["persisted_state"]["work"]["state"] == "DONE"
    assert execute_run(case, run, settings)["claimed"] is False  # nothing left to claim
    assert dispatch_due(client, settings)["eligible"] == 0
    assert len(posts(case, "/capture")) == 1 and work(case).state == "DONE" and work(case).claim_token is None


def test_lost_dispatch_response_reuses_the_key_and_early_start_is_harmless(settlement_case):
    case = settlement_case(n=1, price=100)
    with_due_work(case)
    settings = configured(case)
    client = fake_client()
    # Pin both ticks inside one 10-minute idempotency bucket (bucket rollover is tested separately).
    start = (int(utcnow().timestamp()) // BUCKET_SECONDS + 1) * BUCKET_SECONDS + 60
    now = datetime.fromtimestamp(start, tz=timezone.utc)
    client.workflows.lose_responses = 1
    first = dispatch_due(client, settings, now=now)
    assert first["submitted"] == 0 and first["failed"] == 1 and len(client.workflows.runs) == 1  # created, response lost
    second = dispatch_due(client, settings, now=now + timedelta(seconds=30))
    assert second["submitted"] == 1 and len(client.workflows.runs) == 1  # same key -> original run
    assert client.workflows.calls[0]["key"] == client.workflows.calls[1]["key"]
    run = next(iter(client.workflows.runs.values()))
    # The run starts before the dispatcher saw any response: the database decides, not dispatch state.
    assert execute_run(case, run, settings)["persisted_state"]["campaign"] == "CONFIRMED"
    # The confirming pass re-armed the row (new version), so a later tick dispatches one follow-up run.
    later = dispatch_due(client, settings, now=now + timedelta(minutes=11))
    assert later["submitted"] == 1 and len(client.workflows.runs) == 2
    follow_up = client.workflows.runs[client.workflows.calls[-1]["key"]]
    assert execute_run(case, follow_up, settings)["persisted_state"]["work"]["state"] == "DONE"
    assert dispatch_due(client, settings, now=now + timedelta(minutes=22))["eligible"] == 0
    # Re-delivering either run after completion causes no financial effect.
    assert execute_run(case, run, settings)["claimed"] is False
    assert execute_run(case, follow_up, settings)["claimed"] is False
    assert len(posts(case, "/capture")) == 1


def test_worker_stops_mid_pass_and_recovery_is_retrieval_only(settlement_case):
    case = settlement_case(n=1, price=100)
    with_due_work(case)
    settings = configured(case)
    client = fake_client()
    dispatch_due(client, settings)
    run = next(iter(client.workflows.runs.values()))
    case.provider.crash_capture.add(case.rows[0].id)
    with pytest.raises(SimulatedWorkerDeath):  # provider captured; worker died before persisting
        execute_run(case, run, settings)
    stuck = work(case)
    assert stuck.state == "LEASED" and stuck.claim_token is not None
    assert dispatch_due(client, settings)["eligible"] == 0  # live lease: not re-dispatched yet
    with SessionLocal() as db:  # simulate elapsed lease time for the work row and the capture operation
        db.get(SettlementWork, stuck.id).lease_expires_at = utcnow() - timedelta(seconds=1)
        op = db.scalar(select(PaymentOperation).where(PaymentOperation.booking_id == case.rows[0].id,
                                                      PaymentOperation.kind == "CAPTURE"))
        op.lease_expires_at, request_id = utcnow() - timedelta(seconds=1), op.request_id
        db.commit()
    retry = dispatch_due(client, settings)
    assert retry["submitted"] == 1 and len(client.workflows.runs) == 2  # new version -> new key
    rerun = client.workflows.runs[client.workflows.calls[-1]["key"]]
    assert execute_run(case, rerun, settings)["persisted_state"]["campaign"] == "CONFIRMED"
    captures = posts(case, "/capture")
    assert len(captures) == 1 and captures[0][2] == str(request_id)  # no second POST; same request ID
    with SessionLocal() as db:
        assert len(list(db.scalars(select(PaymentOperation).where(
            PaymentOperation.booking_id == case.rows[0].id, PaymentOperation.kind == "CAPTURE")))) == 1


def test_operator_cleanup_work_is_never_dispatched_or_claimed(settlement_case):
    case = confirmed(settlement_case)
    from tipping_point.settlement.operator_cleanup import request_cleanup
    with SessionLocal() as db:
        request_cleanup(db, case.settings, req(case))
    cleanup = work(case)
    assert cleanup.purpose == CLEANUP_PURPOSE and cleanup.state == "READY"
    settings = configured(case, mode="enabled", campaigns=[])
    with SessionLocal() as db:
        assert eligible_work(db, settings, now=utcnow() + timedelta(hours=1), limit=40) == []
    client = fake_client()
    assert dispatch_due(client, settings, now=utcnow() + timedelta(hours=1))["eligible"] == 0
    assert client.workflows.calls == []
    calls_before = len(case.provider.calls)
    result = run_task(case, str(case.campaign_id), settings)  # even a direct remote task cannot claim it
    assert result["claimed"] is False and case.provider.calls[calls_before:] == []
    after = work(case)
    assert (after.purpose, after.state, after.version, after.claim_token) == (CLEANUP_PURPOSE, "READY", cleanup.version, None)
    assert status(case) == "COMPENSATING" and not posts(case, "/refund")
    assert REASON  # cleanup intent recorded by the operator path only


def test_secrets_and_buyer_details_never_appear_in_payloads_results_or_logs(settlement_case, caplog):
    case = settlement_case(n=1, price=100)
    with_due_work(case)
    canary_secret, canary_payee = "SECRET-CANARY-" + uuid.uuid4().hex, "PAYEE-CANARY-" + uuid.uuid4().hex
    settings = configured(case, paypal_client_secret=SecretStr(canary_secret), paypal_expected_payee=canary_payee)
    gateway = PayPalGateway.from_settings(settings, transport=httpx.MockTransport(case.provider))
    client = fake_client()
    caplog.set_level(logging.DEBUG, logger="tipping_point")
    summary = dispatch_due(client, settings)
    run = next(iter(client.workflows.runs.values()))
    result = run_task(case, run.input["campaign_id"], settings, gateway=gateway)
    asyncio.run(gateway.aclose())
    report = readiness_report(settings=settings)
    assert all(set(call["input"]) == {"campaign_id"} for call in client.workflows.calls)
    records = " ".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    blob = json.dumps([summary, result, report, client.workflows.calls], default=str) + records
    for secret in (canary_secret, canary_payee, "offline@example.test", case.rows[0].order_id, case.rows[0].auth_id,
                   "offline-only", str(settings.paypal_client_id)):
        assert secret not in blob
    assert result["persisted_state"]["campaign"] == "CONFIRMED"


def test_readiness_diagnostic_is_read_only_and_reports_booleans(owned):
    with SessionLocal() as db:
        counts = {t: db.scalar(select(__import__("sqlalchemy").func.count()).select_from(m)) for t, m in
                  (("work", SettlementWork), ("operations", PaymentOperation), ("campaigns", Campaign))}
    from tipping_point.settings import AppSettings
    report = readiness_report(settings=AppSettings(_env_file=None, allow_insecure_dev_cookies=True))
    assert report["database_reachable"] and report["schema_revision_matches"] and report["settlement_schema_present"]
    assert report["financial_operations_performed"] == 0 and report["remote_financial_execution_enabled"] is False
    assert set(report) <= {"task", "app_version", "git_commit", "python", "expected_schema_revision", "database_reachable",
                           "schema_revision_matches", "settlement_schema_present", "paypal_sandbox_credentials_present",
                           "remote_financial_execution_enabled", "financial_operations_performed"}
    with SessionLocal() as db:
        assert counts == {t: db.scalar(select(__import__("sqlalchemy").func.count()).select_from(m)) for t, m in
                          (("work", SettlementWork), ("operations", PaymentOperation), ("campaigns", Campaign))}
    app = create_app(AppSettings(_env_file=None, allow_insecure_dev_cookies=True))
    ready = TestClient(app).get("/health/ready")
    assert ready.status_code == 200 and ready.json() == {"status": "ready", "database": True, "schema": True}


def test_rejected_submission_returned_by_the_sdk_is_not_counted_as_dispatched(settlement_case):
    """render==1.8.0's sync start_task returns an Error model (or None) for 4xx/429 instead of raising."""
    from render.public_api.models.error import Error
    case = settlement_case(n=1, price=100)
    with_due_work(case)
    settings = configured(case)
    from render.public_api.models.task_run import TaskRun
    assert "status" in TaskRun.__annotations__ and "status" not in Error.__annotations__
    for rejected in (Error.from_dict({"id": "unauthorized", "message": "rejected"}),
                     Error.from_dict({"id": "trn-lookalike", "message": "rate limited"}), None):
        client = SimpleNamespace(workflows=SimpleNamespace(start_task=lambda *a, **k: rejected))
        summary = dispatch_due(client, settings)
        assert summary["eligible"] == 1 and summary["submitted"] == 0 and summary["failed"] == 1 and summary["runs"] == []
    assert work(case).state == "READY" and work(case).version == 0 and case.provider.calls == []
