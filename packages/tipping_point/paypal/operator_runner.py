"""Explicit, resumable operator workflow for one PayPal Sandbox authorization test.

This module is intentionally not imported by the application.  It never makes a
network request unless an operator explicitly selects a non-preflight stage and
passes ``--allow-network`` to the script wrapper.  The local JSON record is test
evidence only; it is not a booking/payment persistence model.
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import httpx

from ..settings import AppSettings
from .client import (
    PAYPAL_INTENT_AUTHORIZE,
    PayPalAuthorization,
    PayPalGateway,
    PayPalOrder,
    PayPalOutcomeUnknownError,
    PayPalVoidResult,
    format_minor_to_amount,
)

PRIVATE_RUN_DIRECTORY = Path(".private/paypal-sandbox-runs")
APPROVAL_HOST = "www.sandbox.paypal.com"
RUN_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
Stage = Literal[
    "preflight",
    "create",
    "inspect-order",
    "authorize",
    "inspect-authorization",
    "void",
    "verify-void",
]


class OperatorRunError(RuntimeError):
    """A safe-to-display operator workflow error."""


@dataclass
class OperatorRunRecord:
    """Non-secret, resumable state for one explicitly approved Sandbox test."""

    test_run_id: str
    expected_amount_minor: int
    expected_currency: str
    expected_reference_id: str
    expected_payee: str
    created_at: str
    operations: dict[str, dict[str, object]] = field(default_factory=dict)
    provider_order_id: str | None = None
    provider_authorization_id: str | None = None
    order_validated_at: str | None = None
    latest_outcome: str = "prepared"


def utc_now() -> str:
    """Return a stable UTC timestamp for local operator evidence."""
    return datetime.now(timezone.utc).isoformat()


def validate_run_id(run_id: str) -> str:
    """Require a filesystem-safe, human-selected run identifier."""
    normalized = run_id.strip().lower()
    if not RUN_ID_PATTERN.fullmatch(normalized):
        raise OperatorRunError("run ID must be 3-64 lowercase letters, digits, or hyphens")
    return normalized


def validate_approval_url(url: str | None) -> str:
    """Accept only a provider-returned HTTPS PayPal Sandbox approval link."""
    if not isinstance(url, str) or not url.strip():
        raise OperatorRunError("PayPal did not return an approval link")
    parsed = urlsplit(url.strip())
    if (
        parsed.scheme != "https"
        or parsed.hostname != APPROVAL_HOST
        or parsed.username is not None
        or parsed.password is not None
        or not parsed.path
    ):
        raise OperatorRunError("PayPal approval link was not an HTTPS Sandbox destination")
    return url.strip()


def _record_path(run_id: str, root: Path = PRIVATE_RUN_DIRECTORY) -> Path:
    return root / f"{validate_run_id(run_id)}.json"


def _require_ignored(path: Path) -> None:
    """Refuse to persist test evidence unless Git ignores the target path."""
    result = subprocess.run(
        ["git", "check-ignore", "-q", str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise OperatorRunError("refusing to write: the local run record path is not Git-ignored")


def load_or_create_record(
    *,
    run_id: str,
    expected_amount_minor: int,
    expected_reference_id: str,
    expected_payee: str,
    root: Path = PRIVATE_RUN_DIRECTORY,
) -> OperatorRunRecord:
    """Load a run exactly, or create its non-secret expected-state record."""
    path = _record_path(run_id, root)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            record = OperatorRunRecord(**data)
        except (OSError, ValueError, TypeError) as exc:
            raise OperatorRunError("local run record is unreadable; do not create a replacement") from exc
        expected = (expected_amount_minor, "GBP", expected_reference_id, expected_payee)
        observed = (
            record.expected_amount_minor,
            record.expected_currency,
            record.expected_reference_id,
            record.expected_payee,
        )
        if observed != expected:
            raise OperatorRunError("run metadata differs from the existing record; do not replace it")
        return record
    if expected_amount_minor != 100:
        raise OperatorRunError("this prepared operator test permits GBP 1.00 only")
    if not expected_reference_id.strip() or not expected_payee.strip():
        raise OperatorRunError("reference ID and expected payee are required")
    return OperatorRunRecord(
        test_run_id=validate_run_id(run_id),
        expected_amount_minor=expected_amount_minor,
        expected_currency="GBP",
        expected_reference_id=expected_reference_id.strip(),
        expected_payee=expected_payee.strip(),
        created_at=utc_now(),
    )


def save_record(record: OperatorRunRecord, root: Path = PRIVATE_RUN_DIRECTORY) -> Path:
    """Atomically save non-secret operator evidence after ignore verification."""
    path = _record_path(record.test_run_id, root)
    _require_ignored(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(asdict(record), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)
    return path


def prepare_mutation(
    record: OperatorRunRecord, *, operation: str, payload: dict[str, object]
) -> str:
    """Persist/reuse one immutable logical mutation and its request identifier."""
    if record.latest_outcome == "unknown":
        raise OperatorRunError("a prior mutation is unknown; reconcile by retrieval before any mutation")
    existing = record.operations.get(operation)
    if existing is not None:
        if existing.get("payload") != payload:
            raise OperatorRunError("existing operation payload differs; do not create a replacement")
        request_id = existing.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            raise OperatorRunError("existing operation record is unusable; do not create a replacement")
        return request_id
    request_id = f"sandbox-{record.test_run_id}-{operation}-{uuid.uuid4().hex[:16]}"
    record.operations[operation] = {
        "operation": operation,
        "request_id": request_id,
        "payload": payload,
        "outcome": "prepared",
        "prepared_at": utc_now(),
    }
    record.latest_outcome = "prepared"
    return request_id


def mark_operation(
    record: OperatorRunRecord, *, operation: str, outcome: str, result: dict[str, object]
) -> None:
    """Record a sanitized observed or unknown outcome without request secrets."""
    entry = record.operations[operation]
    entry["outcome"] = outcome
    entry["result"] = result
    entry["updated_at"] = utc_now()
    record.latest_outcome = outcome


def validate_order(record: OperatorRunRecord, order: PayPalOrder) -> None:
    """Validate provider state required before authorization; browser params never count."""
    if order.provider_order_id != record.provider_order_id:
        raise OperatorRunError("retrieved order ID does not match this test record")
    if order.intent != PAYPAL_INTENT_AUTHORIZE:
        raise OperatorRunError("retrieved order intent is not AUTHORIZE")
    if order.amount_minor != record.expected_amount_minor or order.currency != "GBP":
        raise OperatorRunError("retrieved order amount/currency does not match GBP 1.00")
    if order.reference_id != record.expected_reference_id:
        raise OperatorRunError("retrieved purchase-unit reference does not match")
    if order.payee_identifier != record.expected_payee:
        raise OperatorRunError("retrieved purchase-unit payee does not match")
    if order.status != "APPROVED":
        raise OperatorRunError("retrieved order is not in APPROVED state; authorization is not permitted")


def validate_authorization(record: OperatorRunRecord, authorization: PayPalAuthorization) -> None:
    """Validate the retrieved authorization belongs to this test before cleanup."""
    if authorization.authorization_id != record.provider_authorization_id:
        raise OperatorRunError("retrieved authorization ID does not match this test record")
    if authorization.order_id != record.provider_order_id:
        raise OperatorRunError("retrieved authorization is not linked to this test order")
    if authorization.amount_minor != record.expected_amount_minor or authorization.currency != "GBP":
        raise OperatorRunError("retrieved authorization amount/currency does not match GBP 1.00")
    if authorization.status not in {"CREATED", "PENDING", "AUTHORIZED"}:
        raise OperatorRunError("retrieved authorization is not an uncaptured state eligible for void")


async def run_stage(
    *,
    stage: Stage,
    record: OperatorRunRecord,
    settings: AppSettings,
    allow_network: bool,
    root: Path = PRIVATE_RUN_DIRECTORY,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    """Run one explicit stage; preflight is offline and every other stage is gated."""
    if stage == "preflight":
        return (
            "preflight: offline; "
            f"credentials_configured={str(settings.has_paypal_credentials).lower()}; "
            "no PayPal request was made"
        )
    if not allow_network:
        raise OperatorRunError("network stages require explicit --allow-network after approval")
    if not settings.has_paypal_credentials:
        raise OperatorRunError("PayPal Sandbox credentials are not configured on the server")
    async with PayPalGateway.from_settings(settings, transport=transport) as gateway:
        if stage == "create":
            request_id = prepare_mutation(
                record,
                operation="create",
                payload={
                    "intent": "AUTHORIZE",
                    "purchase_units": [{
                        "reference_id": record.expected_reference_id,
                        "amount": {"currency_code": "GBP", "value": format_minor_to_amount(100, "GBP")},
                    }],
                },
            )
            save_record(record, root)
            try:
                order = await gateway.create_authorization_order(
                    reference_id=record.expected_reference_id,
                    amount_minor=100,
                    currency="GBP",
                    operation_id=request_id,
                )
            except PayPalOutcomeUnknownError:
                mark_operation(record, operation="create", outcome="unknown", result={})
                save_record(record, root)
                raise OperatorRunError("create outcome is unknown; reconcile before any further mutation")
            record.provider_order_id = order.provider_order_id
            try:
                approval_url = validate_approval_url(order.approve_url)
            except OperatorRunError:
                mark_operation(
                    record,
                    operation="create",
                    outcome="unknown",
                    result={"order_id": order.provider_order_id},
                )
                save_record(record, root)
                raise OperatorRunError(
                    "create response approval link was unusable; reconcile this order before any mutation"
                )
            mark_operation(record, operation="create", outcome="observed", result={"order_id": order.provider_order_id})
            save_record(record, root)
            return f"create observed; open this provider-returned approval link: {approval_url}"
        if stage == "inspect-order":
            if not record.provider_order_id:
                raise OperatorRunError("no recorded order ID; run create once, then approve in the browser")
            order = await gateway.get_order(record.provider_order_id)
            validate_order(record, order)
            record.order_validated_at = utc_now()
            save_record(record, root)
            return "inspect-order observed: APPROVED order matches the prepared test"
        if stage == "authorize":
            if not record.provider_order_id:
                raise OperatorRunError("no recorded order ID")
            if not record.order_validated_at:
                raise OperatorRunError("inspect-order must validate the approved order before authorization")
            request_id = prepare_mutation(
                record, operation="authorize", payload={"order_id": record.provider_order_id}
            )
            save_record(record, root)
            try:
                order = await gateway.authorize_order(record.provider_order_id, operation_id=request_id)
            except PayPalOutcomeUnknownError:
                mark_operation(record, operation="authorize", outcome="unknown", result={})
                save_record(record, root)
                raise OperatorRunError("authorization outcome is unknown; reconcile order before any mutation")
            if not order.authorizations:
                mark_operation(record, operation="authorize", outcome="unknown", result={})
                save_record(record, root)
                raise OperatorRunError("authorization response was unusable; reconcile order before any mutation")
            record.provider_authorization_id = order.authorizations[0].authorization_id
            mark_operation(record, operation="authorize", outcome="observed", result={"authorization_id": record.provider_authorization_id})
            save_record(record, root)
            return "authorize observed; authorization ID was saved before follow-up validation"
        if stage == "inspect-authorization":
            if not record.provider_authorization_id:
                raise OperatorRunError("no recorded authorization ID; do not create another order")
            authorization = await gateway.get_authorization(record.provider_authorization_id)
            validate_authorization(record, authorization)
            return "inspect-authorization observed: uncaptured authorization matches the prepared test"
        if stage == "void":
            if not record.provider_authorization_id:
                raise OperatorRunError("no recorded authorization ID; refusing to void an unrelated resource")
            request_id = prepare_mutation(
                record,
                operation="void",
                payload={"authorization_id": record.provider_authorization_id},
            )
            save_record(record, root)
            try:
                result: PayPalVoidResult = await gateway.void_authorization(
                    record.provider_authorization_id, operation_id=request_id
                )
            except PayPalOutcomeUnknownError:
                mark_operation(record, operation="void", outcome="unknown", result={})
                save_record(record, root)
                raise OperatorRunError("void outcome is unknown; reconcile authorization before any mutation")
            mark_operation(record, operation="void", outcome="observed", result={"status": result.status})
            save_record(record, root)
            return "void observed; run verify-void to confirm through retrieval"
        if stage == "verify-void":
            if not record.provider_authorization_id:
                raise OperatorRunError("no recorded authorization ID")
            authorization = await gateway.get_authorization(record.provider_authorization_id)
            if authorization.status != "VOIDED":
                raise OperatorRunError("void remains unresolved: retrieval did not confirm VOIDED")
            return "verify-void observed: authorization is VOIDED"
    raise OperatorRunError(f"unsupported stage: {stage}")


def run_stage_sync(**kwargs: object) -> str:
    """Synchronous command wrapper for the one async stage execution."""
    return asyncio.run(run_stage(**kwargs))