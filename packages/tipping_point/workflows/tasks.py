"""Render Workflow task bodies: thin adapters over the existing settlement services.

No Render SDK import here, so these bodies are testable offline. ``render_app``
registers them with the SDK.

Invariants:
- Input is one persisted campaign reference (a UUID string). Credentials,
  buyer details, amounts and provider operations are never task arguments;
  everything financial is read from the database and frozen terms.
- The database is the source of truth. Task completion only means the bounded
  pass ran; the returned ``persisted_state`` is what the database says now.
- Duplicate or retried runs are made harmless by the existing work claims,
  leases, version fencing, operation request IDs and retrieval-only
  reconciliation, not by any "exactly once" assumption.
- Operator-test cleanup work is never claimed here (generic claims exclude it).
- Remote financial execution is refused unless enabled server-side.
"""

from __future__ import annotations

import logging
import platform
import uuid
from contextlib import contextmanager
from typing import Any, Callable

from sqlalchemy import select, text

from .. import __version__

log = logging.getLogger("tipping_point.workflows")

#: Alembic revision this code expects; tests assert it equals the migration head.
EXPECTED_SCHEMA_REVISION = "0007_workshop_visibility"

SETTLE_TASK = "settle_campaign"
DIAGNOSTIC_TASK = "readiness_diagnostic"


class TaskInputError(ValueError):
    """Rejected task input; never echoes the submitted value."""


def parse_campaign_reference(value: Any) -> str:
    """Accept exactly one canonical campaign UUID string; nothing else."""
    if not isinstance(value, str) or len(value) != 36:
        raise TaskInputError("campaign_id must be a canonical UUID string")
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        raise TaskInputError("campaign_id must be a canonical UUID string") from None
    if str(parsed) != value:
        raise TaskInputError("campaign_id must be a canonical UUID string")
    return str(parsed)


@contextmanager
def _default_session():
    from ..db.session import SessionLocal
    with SessionLocal() as db:
        yield db


def _default_gateway(settings):
    from ..paypal.client import PayPalGateway
    return PayPalGateway.from_settings(settings)


def _git_commit() -> str | None:
    import os
    commit = os.environ.get("RENDER_GIT_COMMIT", "").strip()
    return commit[:12] if commit else None


def readiness_report(*, settings=None, session_factory: Callable = _default_session) -> dict:
    """Harmless diagnostic: booleans and versions only.

    Performs no financial operation, no provider call and no write, and returns
    no configuration values or private records.
    """
    from ..settings import AppSettings
    settings = settings or AppSettings()
    report = {
        "task": DIAGNOSTIC_TASK, "app_version": __version__, "git_commit": _git_commit(),
        "python": platform.python_version(), "expected_schema_revision": EXPECTED_SCHEMA_REVISION,
        "database_reachable": False, "schema_revision_matches": False, "settlement_schema_present": False,
        "paypal_sandbox_credentials_present": settings.has_paypal_credentials and settings.paypal_env == "sandbox",
        "remote_financial_execution_enabled": settings.remote_settlement_mode != "disabled",
        "financial_operations_performed": 0,
    }
    try:
        with session_factory() as db:
            db.execute(text("SET TRANSACTION READ ONLY"))
            revision = db.scalar(text("SELECT version_num FROM alembic_version"))
            report["database_reachable"] = True
            report["schema_revision_matches"] = revision == EXPECTED_SCHEMA_REVISION
            report["settlement_schema_present"] = bool(db.scalar(text(
                "SELECT to_regclass('settlement_work') IS NOT NULL AND to_regclass('campaign_decisions') IS NOT NULL")))
            db.rollback()
    except Exception as error:  # report the class only; never connection details
        report["database_error"] = type(error).__name__
    log.info("readiness diagnostic completed", extra={"tp_task": DIAGNOSTIC_TASK})
    return report


async def settle_campaign_pass(
    campaign_id: Any, *, settings=None, session_factory: Callable = _default_session,
    gateway_factory: Callable = _default_gateway,
) -> dict:
    """One bounded, campaign-scoped settlement pass through the existing dispatcher.

    Covers deadline decision freeze, settlement progress, compensation and
    retrieval-only reconciliation exactly as ``process_due`` does locally.
    """
    from ..settings import AppSettings
    from ..db.models import Campaign, SettlementWork
    from ..settlement.decision import schema_available
    from ..settlement.dispatch import process_due

    reference = parse_campaign_reference(campaign_id)
    settings = settings or AppSettings()
    result = {"task": SETTLE_TASK, "campaign_id": reference, "financial_execution": "refused",
              "note": "Task completion is not workshop confirmation; persisted_state is authoritative."}
    if not settings.remote_settlement_permits(reference):
        result["reason"] = ("REMOTE_SETTLEMENT_DISABLED" if settings.remote_settlement_mode == "disabled"
                            else "CAMPAIGN_NOT_ALLOWLISTED")
        log.info("settlement pass refused", extra={"tp_task": SETTLE_TASK, "tp_reason": result["reason"]})
        return result
    if settings.paypal_env != "sandbox" or not settings.has_paypal_credentials:
        result["reason"] = "SANDBOX_NOT_CONFIGURED"
        return result
    with session_factory() as db:
        if not schema_available(db):
            db.rollback()
            result["reason"] = "SCHEMA_UNAVAILABLE"
            return result
        db.commit()
        gateway = gateway_factory(settings)
        try:
            outcomes = await process_due(db, settings, gateway, limit=1, campaign_id=uuid.UUID(reference))
        finally:
            close = getattr(gateway, "aclose", None)
            if close is not None and gateway_factory is _default_gateway:
                await close()
        campaign = db.get(Campaign, uuid.UUID(reference), populate_existing=True)
        work = db.scalar(select(SettlementWork).where(SettlementWork.campaign_id == uuid.UUID(reference))
                         .execution_options(populate_existing=True))
        persisted = {  # read before rollback expires the instances
            "campaign": campaign.status if campaign else None,
            "work": None if work is None else {"purpose": work.purpose, "state": work.state, "version": work.version},
        }
        db.rollback()
    result.update({
        "financial_execution": "permitted",
        "claimed": bool(outcomes),
        "pass_errors": sorted({o["error"] for o in outcomes if "error" in o}),
        "persisted_state": persisted,
    })
    log.info("settlement pass finished", extra={"tp_task": SETTLE_TASK, "tp_claimed": bool(outcomes)})
    return result
