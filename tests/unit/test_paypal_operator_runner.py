"""Offline tests for the explicit operator-only PayPal Sandbox runner."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from tipping_point.paypal.operator_runner import (
    OperatorRunError,
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