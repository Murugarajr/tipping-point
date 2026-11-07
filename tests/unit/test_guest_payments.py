import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import uuid

import httpx
import pytest

from tipping_point.guest.payments import (
    BookingPaymentService, validate_authorization, validate_authorization_association, validate_order,
)
from tipping_point.guest.service import payload_hash
from tipping_point.paypal.client import (
    PayPalGateway, build_authorization_order_payload, parse_authorization, parse_order,
    validate_sandbox_approve_url,
)


def booking():
    return SimpleNamespace(
        id=uuid.uuid4(), amount_minor=2500, currency="GBP", expected_payee="PAYEE",
        provider_order_id="ORDER", provider_authorization_id="AUTH",
        created_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )


def order_for(row):
    return parse_order({
        "id": "ORDER", "status": "APPROVED", "intent": "AUTHORIZE",
        "purchase_units": [{"reference_id": str(row.id), "payee": {"merchant_id": "PAYEE"},
                            "amount": {"currency_code": "GBP", "value": "25.00"}}],
        "links": [{"rel": "payer-action", "href": "https://www.sandbox.paypal.com/checkoutnow?token=ORDER"}],
    })


def authorization_for(row, **changes):
    now = datetime.now(timezone.utc)
    result = parse_authorization({
        "id": "AUTH", "status": "CREATED",
        "amount": {"currency_code": "GBP", "value": "25.00"},
        "supplementary_data": {"related_ids": {"order_id": "ORDER"}},
        "create_time": now.isoformat(), "expiration_time": (now + timedelta(days=29)).isoformat(),
    })
    return replace(result, **changes)


@pytest.mark.parametrize("change", [
    {"purchase_unit_count": 2}, {"purchase_unit_count": 0},
    {"reference_id": "foreign"}, {"payee_identifier": "FOREIGN", "payee_identifiers": ("FOREIGN",)},
    {"amount_minor": 1}, {"currency": "USD"}, {"intent": "CAPTURE"}, {"provider_order_id": "FOREIGN"},
])
def test_strict_order_validation_rejects_every_ambiguity(change):
    row = booking()
    order = order_for(row)
    validate_order(row, order, expected_order_id="ORDER")
    with pytest.raises(ValueError):
        validate_order(row, replace(order, **change), expected_order_id="ORDER")


@pytest.mark.parametrize("change", [
    {"authorization_id": "FOREIGN"}, {"order_id": "FOREIGN"}, {"amount_minor": 1},
    {"currency": "USD"}, {"status": "PENDING"}, {"status": "VOIDED"}, {"create_time": None},
    {"create_time": datetime.now(timezone.utc) - timedelta(days=4)},
    {"expiration_time": datetime.now(timezone.utc) + timedelta(hours=1)},
])
def test_authorization_needs_identity_money_usable_status_and_honor_buffer(change):
    row = booking()
    campaign = SimpleNamespace(cutoff_at=datetime.now(timezone.utc) + timedelta(hours=36), settlement_deadline=None)
    settings = SimpleNamespace(authorization_safety_buffer_hours=6)
    validate_authorization(row, authorization_for(row), campaign, settings)
    with pytest.raises(ValueError):
        validate_authorization(row, authorization_for(row, **change), campaign, settings)


def test_wrong_voided_resource_never_passes_terminal_association_check():
    row = booking()
    with pytest.raises(ValueError):
        validate_authorization_association(row, authorization_for(row, status="VOIDED", authorization_id="FOREIGN"))
    validate_authorization_association(row, authorization_for(row, status="VOIDED"))


@pytest.mark.parametrize("url", [
    "https://www.paypal.com/checkoutnow?token=ORDER",
    "https://www.sandbox.paypal.com.evil.test/?token=ORDER",
    "https://www.sandbox.paypal.com/?token=OTHER",
    "https://www.sandbox.paypal.com/?token=ORDER&token=OTHER",
    "http://www.sandbox.paypal.com/?token=ORDER",
    "https://www.sandbox.paypal.com:443/?token=ORDER",
])
def test_approval_url_has_exact_sandbox_host_scheme_and_order_token(url):
    with pytest.raises(ValueError):
        validate_sandbox_approve_url(url, "ORDER")


def test_payload_builder_matches_gateway_http_body_exactly_and_preserves_operator_default():
    args = dict(reference_id="booking", amount_minor=2500, currency="GBP",
                expected_payee="PAYEE", return_url="https://app.test/return", cancel_url="https://app.test/cancel")
    payload = build_authorization_order_payload(**args)
    assert "payment_source" not in build_authorization_order_payload(reference_id="standalone", amount_minor=2500, currency="GBP")
    requests = []

    def transport(request):
        import json
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "offline", "expires_in": 3600})
        requests.append(json.loads(request.content))
        assert request.headers["PayPal-Request-Id"] == "stable-operation"
        return httpx.Response(201, json={"id": "ORDER", "status": "CREATED"})

    async def run():
        async with PayPalGateway(client_id="offline", client_secret="offline",
                                 transport=httpx.MockTransport(transport)) as gateway:
            await gateway.create_authorization_order(**args, operation_id="stable-operation")
    asyncio.run(run())
    assert requests == [payload]
    assert payload_hash(requests[0]) == payload_hash(payload)


@pytest.mark.parametrize("state", ["AUTHORIZED", "VOIDED"])
def test_repeated_reconciliation_does_not_regress_established_terminal_state(state):
    row = booking()
    row.state = state
    commits = []
    service = BookingPaymentService(SimpleNamespace(commit=lambda: commits.append(True)), None, None)
    service._booking = lambda *args, **kwargs: row
    service._result = lambda _: row
    assert asyncio.run(service.reconcile(row.id)).state == state
    assert commits


def test_claim_is_committed_and_unknown_mutations_are_not_replaced():
    """Exercise claim decisions offline without pretending to prove PG locking."""
    now = datetime.now(timezone.utc)
    row = SimpleNamespace(id=uuid.uuid4(), state="CHECKOUT_RESERVED")
    operation = SimpleNamespace(
        id=uuid.uuid4(), booking_id=row.id, kind="CREATE_ORDER", resource_scope="",
        request_id=uuid.uuid4(), request_payload={"intent": "AUTHORIZE"},
        state="PREPARED", version=0, claim_token=None, lease_expires_at=None,
    )
    commits = []
    db = SimpleNamespace(commit=lambda: commits.append(True))
    service = BookingPaymentService(db, None, None)
    service._booking = lambda *args, **kwargs: row
    service._operation = lambda *args: operation
    claim = service.claim_operation(row.id, "CREATE_ORDER", "", operation.request_payload)
    assert commits and operation.state == "IN_FLIGHT" and row.state == "AUTHORIZATION_PENDING"
    assert claim.request_id == str(operation.request_id)
    assert service.claim_operation(row.id, "CREATE_ORDER", "", operation.request_payload) is None
    operation.lease_expires_at = now - timedelta(seconds=1)
    assert service.claim_operation(row.id, "CREATE_ORDER", "", operation.request_payload) is None
    assert operation.state == "UNKNOWN" and row.state == "REVIEW_REQUIRED"
    resumed = service.claim_operation(row.id, "CREATE_ORDER", "", operation.request_payload, retrieval=True)
    assert resumed.request_id == claim.request_id and resumed.version > claim.version


@pytest.mark.parametrize("state", ["AUTHORIZED", "VOIDED"])
def test_stale_same_resource_completion_is_audited_without_terminal_regression(state):
    row = booking()
    row.state = state
    events = []
    db = SimpleNamespace(commit=lambda: None)
    service = BookingPaymentService(db, None, None)
    service._record_resources = lambda *args, **kwargs: events.append(kwargs)
    service._booking = lambda *args, **kwargs: row
    service._fenced = lambda claim: (SimpleNamespace(), False)
    service._preserve_order = lambda *args: False
    claim = SimpleNamespace(booking_id=row.id)
    assert service.finish_order(claim, order_for(row), valid=True) is False
    assert events and row.state == state


def test_mismatching_voided_authorization_is_audited_and_queued_not_accepted():
    row = booking()
    now = datetime.now(timezone.utc)
    row.campaign_id, row.state = uuid.uuid4(), "AUTHORIZATION_PENDING"
    row.cancelled_at, row.admitted_at = None, None
    row.reservation_expires_at = now + timedelta(minutes=5)
    campaign = SimpleNamespace(cutoff_at=now + timedelta(hours=1), settlement_deadline=None,
                               id=row.campaign_id, status="OPEN", capacity=1)
    operation = SimpleNamespace(id=uuid.uuid4(), state="IN_FLIGHT")
    observed, queued = [], []
    db = SimpleNamespace(in_transaction=lambda: False, scalar=lambda _: campaign,
                         commit=lambda: None, add=lambda event: None)

    async def get_authorization(_):
        return authorization_for(row, status="VOIDED", authorization_id="FOREIGN")

    service = BookingPaymentService(db, SimpleNamespace(authorization_safety_buffer_hours=6),
                                    SimpleNamespace(get_authorization=get_authorization))
    service._record_resources = lambda *args, **kwargs: observed.append(kwargs)
    service._booking = lambda *args, **kwargs: row
    service._fenced = lambda _: (operation, True)
    service._queue_release = lambda *args: queued.append(args[1])
    order = replace(order_for(row), authorizations=(SimpleNamespace(authorization_id="AUTH"),))
    claim = SimpleNamespace(booking_id=row.id, operation_id=operation.id)
    asyncio.run(service._inspect_authorizations(claim, order))
    assert row.state == "REVIEW_REQUIRED" and row.state != "VOIDED"
    assert observed and set(queued) == {"AUTH", "FOREIGN"}


def test_release_retrieves_and_validates_order_before_any_void():
    row = booking()
    row.state = "RELEASE_PENDING"
    payload = {"authorization_id": "AUTH", "order_id": "ORDER", "body": {}}
    operation = SimpleNamespace(resource_scope="AUTH", request_payload=payload)
    calls, failures = [], []
    db = SimpleNamespace(scalar=lambda _: None, scalars=lambda _: [operation], commit=lambda: None, in_transaction=lambda: False)

    async def get_order(order_id):
        calls.append(("get_order", order_id))
        return replace(order_for(row), payee_identifier="FOREIGN", payee_identifiers=("FOREIGN",))

    service = BookingPaymentService(db, None, SimpleNamespace(get_order=get_order))
    service._booking = lambda *args, **kwargs: row
    service.claim_operation = lambda *args, **kwargs: SimpleNamespace()
    service._record_resources = lambda *args, **kwargs: None
    service._error = lambda *args: failures.append(args[-1])
    service._result = lambda _: row
    asyncio.run(service.release_pending(row.id))
    assert calls == [("get_order", "ORDER")] and failures


def test_resource_observation_uses_booking_then_operation_lock_order():
    row = booking()
    calls = []
    operation = SimpleNamespace(provider_resource_id=None)
    db = SimpleNamespace(
        add=lambda _: calls.append("audit"),
        scalar=lambda _: (calls.append("operation") or operation),
        commit=lambda: calls.append("commit"),
    )
    service = BookingPaymentService(db, None, None)
    service._booking = lambda *args, **kwargs: (calls.append("booking") or row)
    claim = SimpleNamespace(booking_id=row.id, operation_id=uuid.uuid4(), kind="CREATE_ORDER")
    service._record_resources(claim, order=order_for(row))
    assert calls == ["booking", "audit", "operation", "commit"]


def test_void_representation_for_a_different_resource_stays_unknown():
    from tipping_point.paypal.client import PayPalOutcomeUnknownError

    def transport(request):
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "offline", "expires_in": 3600})
        return httpx.Response(200, json={"id": "FOREIGN", "status": "VOIDED"})

    async def run():
        async with PayPalGateway(client_id="offline", client_secret="offline",
                                 transport=httpx.MockTransport(transport)) as gateway:
            with pytest.raises(PayPalOutcomeUnknownError) as error:
                await gateway.void_authorization("AUTH", operation_id="stable-void-request")
            assert error.value.operation_id == "stable-void-request"
    asyncio.run(run())
