"""Offline tests for the explicit operator-only PayPal Sandbox runner."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from tipping_point.paypal import parse_order
from tipping_point.paypal.operator_runner import (
    OperatorRunError,
    diagnose_order_response,
    load_or_create_record,
    prepare_mutation,
    run_stage,
    save_record,
    validate_authorization,
    validate_approval_url,
)
from tipping_point.settings import AppSettings


def ignored_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / ".private/paypal-sandbox-runs"
    monkeypatch.setattr(
        "tipping_point.paypal.operator_runner._require_ignored", lambda path: None
    )
    return root


def test_preflight_is_offline_and_does_not_construct_a_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = load_or_create_record(
        run_id="offline-preflight",
        expected_amount_minor=100,
        expected_reference_id="operator-test-001",
        expected_payee="sandbox-merchant@example.test",
        root=ignored_root(tmp_path, monkeypatch),
    )
    calls: list[httpx.Request] = []
    result = asyncio.run(run_stage(
        stage="preflight", record=record, settings=AppSettings(_env_file=None),
        allow_network=False, transport=httpx.MockTransport(lambda request: calls.append(request)),
    ))
    assert "no PayPal request was made" in result
    assert calls == []


def test_command_defaults_to_offline_preflight() -> None:
    from scripts.paypal_sandbox_authorization_test import parser

    args = parser().parse_args([
        "--run-id", "default-preflight",
        "--reference-id", "operator-test-001",
        "--expected-payee", "merchant@example.test",
    ])
    assert args.stage == "preflight"


def test_order_structure_diagnostic_allowlists_nested_payment_resources() -> None:
    response = httpx.Response(
        200,
        headers={
            "content-type": "application/json",
            "paypal-debug-id": "diagnostic-fixture-id",
            "x-unrelated-header": "must-not-be-reported",
        },
        json={
            "id": "order-fixture",
            "intent": "AUTHORIZE",
            "status": "COMPLETED",
            "payer": {"email_address": "must-not-be-reported@example.test"},
            "purchase_units": [{
                "reference_id": "operator-test-001",
                "payments": {
                    "authorizations": [{
                        "id": "authorization-fixture",
                        "status": "CREATED",
                        "amount": {"currency_code": "GBP", "value": "1.00"},
                        "seller_protection": {"status": "ELIGIBLE"},
                    }],
                    "captures": [{
                        "id": "capture-fixture",
                        "status": "COMPLETED",
                        "amount": {"currency_code": "GBP", "value": "1.00"},
                        "create_time": "must-not-be-reported",
                    }],
                },
            }],
        },
    )

    diagnostic, payload = diagnose_order_response(response)

    assert payload == response.json()
    assert diagnostic == {
        "http_status": 200,
        "content_type": "application/json",
        "paypal_debug_id": "diagnostic-fixture-id",
        "top_level_field_names": ["id", "intent", "payer", "purchase_units", "status"],
        "order_id": "order-fixture",
        "intent": "AUTHORIZE",
        "order_status": "COMPLETED",
        "purchase_unit_count": 1,
        "purchase_units": [{
            "field_names": ["payments", "reference_id"],
            "payments_kind": "object",
            "payments_field_names": ["authorizations", "captures"],
            "authorizations": {
                "kind": "list",
                "length": 1,
                "resources": [{
                    "id": "authorization-fixture", "status": "CREATED",
                    "amount": "1.00", "currency": "GBP",
                }],
            },
            "captures": {
                "kind": "list",
                "length": 1,
                "resources": [{
                    "id": "capture-fixture", "status": "COMPLETED",
                    "amount": "1.00", "currency": "GBP",
                }],
            },
        }],
    }


@pytest.mark.parametrize(("payments", "payments_kind", "authorization_kind", "capture_kind"), [
    (pytest.param("missing", "absent", "absent", "absent")),
    (pytest.param(None, "null", "absent", "absent")),
    (pytest.param([], "other", "absent", "absent")),
    (pytest.param({"authorizations": None, "captures": {"unexpected": True}}, "object", "null", "invalid")),
])
def test_order_structure_diagnostic_distinguishes_collection_states(
    payments: object,
    payments_kind: str,
    authorization_kind: str,
    capture_kind: str,
) -> None:
    purchase_unit: dict[str, object] = {}
    if payments != "missing":
        purchase_unit["payments"] = payments
    diagnostic, _ = diagnose_order_response(httpx.Response(200, json={
        "id": "order-fixture", "intent": "AUTHORIZE", "status": "COMPLETED",
        "purchase_units": [purchase_unit],
    }))
    unit = diagnostic["purchase_units"][0]
    assert unit["payments_kind"] == payments_kind
    assert unit["authorizations"]["kind"] == authorization_kind
    assert unit["captures"]["kind"] == capture_kind
    assert unit["authorizations"]["length"] is None
    assert unit["captures"]["length"] is None


def test_diagnose_order_persists_only_allowlisted_result_and_stops_after_one_get(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = ignored_root(tmp_path, monkeypatch)
    record = load_or_create_record(
        run_id="diagnose-order", expected_amount_minor=100,
        expected_reference_id="operator-test-001", expected_payee="sandbox-merchant-fixture",
        root=root,
    )
    record.provider_order_id = "order-fixture"
    prepare_mutation(record, operation="authorize", payload={"order_id": "order-fixture"})
    record.operations["authorize"]["outcome"] = "unknown"
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "fixture-token", "expires_in": 3600})
        if request.url.path == "/v2/checkout/orders/order-fixture":
            return httpx.Response(200, headers={"paypal-debug-id": "fixture-debug-id"}, json={
                "id": "order-fixture", "status": "COMPLETED", "intent": "AUTHORIZE",
                "purchase_units": [{
                    "reference_id": "operator-test-001",
                    "payee": {"merchant_id": "sandbox-merchant-fixture"},
                    "amount": {"currency_code": "GBP", "value": "1.00"},
                    "payments": {"authorizations": [], "captures": []},
                }],
                "payer": {"email_address": "must-not-persist@example.test"},
            })
        pytest.fail(f"unexpected request {request.method} {request.url.path}")

    settings = AppSettings(
        _env_file=None, PAYPAL_CLIENT_ID="fixture-id", PAYPAL_CLIENT_SECRET="fixture-secret"
    )
    result = asyncio.run(run_stage(
        stage="diagnose-order", record=record, settings=settings, allow_network=True,
        root=root, transport=httpx.MockTransport(handler),
    ))

    diagnostic = record.operations["diagnose-order"]["result"]
    assert "authorizations=list[0]" in result
    assert "captures=list[0]" in result
    assert "normalized resources match" in result
    assert diagnostic["paypal_debug_id"] == "fixture-debug-id"
    assert "payer" in diagnostic["top_level_field_names"]
    assert "must-not-persist@example.test" not in str(diagnostic)
    assert record.operations["authorize"]["outcome"] == "unknown"
    assert [(request.method, request.url.path) for request in requests] == [
        ("POST", "/v1/oauth2/token"),
        ("GET", "/v2/checkout/orders/order-fixture"),
    ]


def test_diagnose_order_matches_normalized_nested_resources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = ignored_root(tmp_path, monkeypatch)
    record = load_or_create_record(
        run_id="diagnose-mismatch", expected_amount_minor=100,
        expected_reference_id="operator-test-001", expected_payee="sandbox-merchant-fixture",
        root=root,
    )
    record.provider_order_id = "order-fixture"
    prepare_mutation(record, operation="authorize", payload={"order_id": "order-fixture"})
    record.operations["authorize"]["outcome"] = "unknown"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "fixture-token", "expires_in": 3600})
        if request.url.path == "/v2/checkout/orders/order-fixture":
            return httpx.Response(200, json={
                "id": "order-fixture", "status": "COMPLETED", "intent": "AUTHORIZE",
                "purchase_units": [{
                    "reference_id": "operator-test-001",
                    "payee": {"merchant_id": "sandbox-merchant-fixture"},
                    "amount": {"currency_code": "GBP", "value": "1.00"},
                    "payments": {"authorizations": [{
                        "id": "authorization-fixture", "status": "CREATED",
                        "amount": {"currency_code": "GBP", "value": "1.00"},
                    }]},
                }],
            })
        pytest.fail(f"unexpected request {request.method} {request.url.path}")

    settings = AppSettings(
        _env_file=None, PAYPAL_CLIENT_ID="fixture-id", PAYPAL_CLIENT_SECRET="fixture-secret"
    )
    result = asyncio.run(run_stage(
        stage="diagnose-order", record=record, settings=settings, allow_network=True,
        root=root, transport=httpx.MockTransport(handler),
    ))
    diagnostic = record.operations["diagnose-order"]["result"]
    assert "authorizations=list[1]" in result
    assert "normalized resources match" in result
    assert diagnostic["purchase_units"][0]["authorizations"]["resources"] == [{
        "id": "authorization-fixture", "status": "CREATED", "amount": "1.00", "currency": "GBP",
    }]
    assert record.operations["authorize"]["outcome"] == "unknown"


def test_mutation_record_reuses_id_and_refuses_changed_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = ignored_root(tmp_path, monkeypatch)
    record = load_or_create_record(
        run_id="resume-safely", expected_amount_minor=100,
        expected_reference_id="operator-test-001", expected_payee="merchant@example.test", root=root,
    )
    request_id = prepare_mutation(record, operation="create", payload={"amount": "1.00"})
    save_record(record, root)
    resumed = load_or_create_record(
        run_id="resume-safely", expected_amount_minor=100,
        expected_reference_id="operator-test-001", expected_payee="merchant@example.test", root=root,
    )
    assert prepare_mutation(resumed, operation="create", payload={"amount": "1.00"}) == request_id
    with pytest.raises(OperatorRunError, match="payload differs"):
        prepare_mutation(resumed, operation="create", payload={"amount": "2.00"})


def test_approval_url_must_be_provider_returned_https_sandbox_link() -> None:
    assert validate_approval_url("https://www.sandbox.paypal.com/checkoutnow?token=order")
    with pytest.raises(OperatorRunError):
        validate_approval_url("http://www.sandbox.paypal.com/checkoutnow")
    with pytest.raises(OperatorRunError):
        validate_approval_url("https://evil.example/checkoutnow")


def test_network_stage_requires_explicit_future_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = load_or_create_record(
        run_id="network-gate", expected_amount_minor=100,
        expected_reference_id="operator-test-001", expected_payee="merchant@example.test",
        root=ignored_root(tmp_path, monkeypatch),
    )
    with pytest.raises(OperatorRunError, match="--allow-network"):
        asyncio.run(run_stage(
            stage="create", record=record, settings=AppSettings(_env_file=None), allow_network=False
        ))


def test_unknown_outcome_blocks_a_new_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = load_or_create_record(
        run_id="unknown-block", expected_amount_minor=100,
        expected_reference_id="operator-test-001", expected_payee="merchant@example.test",
        root=ignored_root(tmp_path, monkeypatch),
    )
    record.latest_outcome = "unknown"
    with pytest.raises(OperatorRunError, match="reconcile"):
        prepare_mutation(record, operation="create", payload={})


def test_authorize_requires_completed_order_inspection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = load_or_create_record(
        run_id="inspect-before-authorize", expected_amount_minor=100,
        expected_reference_id="operator-test-001", expected_payee="merchant@example.test",
        root=ignored_root(tmp_path, monkeypatch),
    )
    record.provider_order_id = "order-fixture"
    settings = AppSettings(
        _env_file=None, PAYPAL_CLIENT_ID="fixture-id", PAYPAL_CLIENT_SECRET="fixture-secret"
    )
    with pytest.raises(OperatorRunError, match="inspect-order"):
        asyncio.run(run_stage(
            stage="authorize", record=record, settings=settings, allow_network=True,
            transport=httpx.MockTransport(lambda request: pytest.fail("must not send request")),
        ))


def test_authorization_linkage_must_match_the_recorded_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tipping_point.paypal import PayPalAuthorization
    from datetime import datetime, timezone

    record = load_or_create_record(
        run_id="authorization-linkage", expected_amount_minor=100,
        expected_reference_id="operator-test-001", expected_payee="merchant@example.test",
        root=ignored_root(tmp_path, monkeypatch),
    )
    record.provider_order_id = "order-fixture"
    record.provider_authorization_id = "authorization-fixture"
    authorization = PayPalAuthorization(
        authorization_id="authorization-fixture", status="CREATED", order_id="other-order",
        amount_minor=100, currency="GBP", expiration_time=None, create_time=None,
        update_time=None, seller_protection_status=None, links=(),
        retrieved_at=datetime.now(timezone.utc),
    )
    with pytest.raises(OperatorRunError, match="linked"):
        validate_authorization(record, authorization)


def test_reconcile_retrieves_only_order_and_discovered_authorization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = ignored_root(tmp_path, monkeypatch)
    record = load_or_create_record(
        run_id="read-only-reconcile", expected_amount_minor=100,
        expected_reference_id="operator-test-001", expected_payee="sandbox-merchant-fixture",
        root=root,
    )
    record.provider_order_id = "order-fixture"
    prepare_mutation(record, operation="authorize", payload={"order_id": "order-fixture"})
    record.latest_outcome = "unknown"
    record.operations["authorize"]["outcome"] = "unknown"
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={
                "access_token": "fixture-token", "expires_in": 3600,
            })
        if request.url.path == "/v2/checkout/orders/order-fixture":
            return httpx.Response(200, json={
                "id": "order-fixture", "status": "COMPLETED", "intent": "AUTHORIZE",
                "purchase_units": [{
                    "reference_id": "operator-test-001",
                    "payee": {"merchant_id": "sandbox-merchant-fixture"},
                    "amount": {"currency_code": "GBP", "value": "1.00"},
                }],
                "payments": {"authorizations": [{
                    "id": "authorization-fixture", "status": "CREATED",
                    "amount": {"currency_code": "GBP", "value": "1.00"},
                }]},
            })
        if request.url.path == "/v2/payments/authorizations/authorization-fixture":
            return httpx.Response(200, json={
                "id": "authorization-fixture", "status": "CREATED",
                "supplementary_data": {"related_ids": {"order_id": "order-fixture"}},
                "amount": {"currency_code": "GBP", "value": "1.00"},
            })
        pytest.fail(f"unexpected request {request.method} {request.url.path}")

    settings = AppSettings(
        _env_file=None, PAYPAL_CLIENT_ID="fixture-id", PAYPAL_CLIENT_SECRET="fixture-secret"
    )
    result = asyncio.run(run_stage(
        stage="reconcile", record=record, settings=settings, allow_network=True, root=root,
        transport=httpx.MockTransport(handler),
    ))

    assert "status=COMPLETED" in result
    assert "authorization-count=1" in result
    assert "captures=none" in result
    assert record.provider_authorization_id == "authorization-fixture"
    assert record.operations["authorize"]["outcome"] == "reconciled"
    assert [(request.method, request.url.path) for request in requests] == [
        ("POST", "/v1/oauth2/token"),
        ("GET", "/v2/checkout/orders/order-fixture"),
        ("GET", "/v2/payments/authorizations/authorization-fixture"),
    ]


def test_order_parser_exposes_unexpected_capture_resources() -> None:
    order = parse_order({
        "id": "order-fixture", "status": "COMPLETED", "intent": "AUTHORIZE",
        "purchase_units": [],
        "payments": {"captures": [{
            "id": "capture-fixture", "status": "COMPLETED",
            "amount": {"currency_code": "GBP", "value": "1.00"},
        }]},
    })
    assert [(item.capture_id, item.status, item.amount_minor, item.currency) for item in order.captures] == [
        ("capture-fixture", "COMPLETED", 100, "GBP"),
    ]


def test_reconcile_preserves_unknown_when_order_has_no_authorization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = ignored_root(tmp_path, monkeypatch)
    record = load_or_create_record(
        run_id="reconcile-no-authorization", expected_amount_minor=100,
        expected_reference_id="operator-test-001", expected_payee="sandbox-merchant-fixture",
        root=root,
    )
    record.provider_order_id = "order-fixture"
    prepare_mutation(record, operation="authorize", payload={"order_id": "order-fixture"})
    record.latest_outcome = "unknown"
    record.operations["authorize"]["outcome"] = "unknown"
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "fixture-token", "expires_in": 3600})
        if request.url.path == "/v2/checkout/orders/order-fixture":
            return httpx.Response(200, json={
                "id": "order-fixture", "status": "COMPLETED", "intent": "AUTHORIZE",
                "purchase_units": [{
                    "reference_id": "operator-test-001",
                    "payee": {"merchant_id": "sandbox-merchant-fixture"},
                    "amount": {"currency_code": "GBP", "value": "1.00"},
                }],
                "payments": {"authorizations": [], "captures": []},
            })
        pytest.fail(f"unexpected request {request.method} {request.url.path}")

    settings = AppSettings(
        _env_file=None, PAYPAL_CLIENT_ID="fixture-id", PAYPAL_CLIENT_SECRET="fixture-secret"
    )
    result = asyncio.run(run_stage(
        stage="reconcile", record=record, settings=settings, allow_network=True, root=root,
        transport=httpx.MockTransport(handler),
    ))

    assert "authorization-count=0" in result
    assert record.provider_authorization_id is None
    assert record.operations["authorize"]["outcome"] == "unknown"
    assert [(request.method, request.url.path) for request in requests] == [
        ("POST", "/v1/oauth2/token"),
        ("GET", "/v2/checkout/orders/order-fixture"),
    ]