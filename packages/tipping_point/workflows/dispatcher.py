"""Bounded, stateless dispatcher: due settlement work -> Render task runs.

Run by a Render cron job (Render Workflows has no native scheduling). Each tick:

1. In one short READ ONLY transaction, select due, non-cleanup ``settlement_work``
   rows (READY, or LEASED with an expired lease) for permitted campaigns.
2. Close the transaction, then submit at most ``dispatch_batch_limit`` task runs
   with ``{"campaign_id": ...}`` as the only input.

Recoverability without a dispatch table:
- The Render idempotency key is derived from (work id, work version, 10-minute
  bucket). A lost submit response, or a resubmission by the next tick, returns
  the original run instead of creating a new one (Render enforces task
  idempotency keys for 24 hours, scoped to the workflow service).
- Every claim bumps ``version`` and a non-terminal finish moves ``due_at``; the
  next pass therefore gets a fresh key. A run that never started, or failed
  before claiming, is re-dispatched after the bucket rolls over.
- A task that starts before the dispatcher sees the submission response, or a
  run delivered twice, is harmless: claims, leases and version fencing allow one
  worker per campaign, and the payment ledger/provider idempotency prevent
  duplicate financial effects. Execution is at-least-once, never "exactly once".

This module writes nothing to the database and never touches cleanup work.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from sqlalchemy import or_, select, text

from .tasks import SETTLE_TASK

log = logging.getLogger("tipping_point.workflows.dispatcher")

BUCKET_SECONDS = 600


@dataclass(frozen=True)
class DueWork:
    work_id: str
    campaign_id: str
    version: int


def idempotency_key(item: DueWork, now: datetime) -> str:
    bucket = int(now.timestamp()) // BUCKET_SECONDS
    return f"tp-settle:{item.work_id}:v{item.version}:b{bucket}"


def eligible_work(db, settings, *, now: datetime, limit: int) -> list[DueWork]:
    """Read-only selection of permitted due work; cleanup work is always excluded."""
    from ..db.models import SettlementWork
    from ..settlement.decision import CLEANUP_PURPOSE

    if settings.remote_settlement_mode != "campaign_allowlist":
        return []  # fail closed: only an exact allowlist ever selects work
    allowed = sorted(settings.remote_settlement_campaigns)
    if not allowed:
        return []
    query = select(SettlementWork.id, SettlementWork.campaign_id, SettlementWork.version).where(
        SettlementWork.campaign_id.in_(allowed),
        SettlementWork.purpose != CLEANUP_PURPOSE,
        SettlementWork.due_at <= now,
        or_(SettlementWork.state == "READY",
            (SettlementWork.state == "LEASED") & (SettlementWork.lease_expires_at <= now)),
    )
    rows = db.execute(query.order_by(SettlementWork.due_at, SettlementWork.id).limit(limit)).all()
    return [DueWork(str(w), str(c), v) for w, c, v in rows]


def dispatch_due(client: Any, settings, *, session_factory: Callable | None = None,
                 now: datetime | None = None) -> dict:
    """Submit task runs for due work. ``client`` is a Render SDK client (or a test double)."""
    from ..guest.service import utcnow
    from .tasks import _default_session

    now = now or utcnow()
    summary = {"mode": settings.remote_settlement_mode, "eligible": 0, "submitted": 0, "failed": 0, "runs": []}
    if settings.remote_settlement_mode != "campaign_allowlist" or not settings.remote_settlement_campaigns:
        log.info("dispatch skipped: remote settlement disabled or allowlist empty")
        return summary
    if not settings.render_workflow_slug:
        raise RuntimeError("TIPPING_POINT_RENDER_WORKFLOW_SLUG is required to dispatch")
    with (session_factory or _default_session)() as db:
        db.execute(text("SET TRANSACTION READ ONLY"))
        items = eligible_work(db, settings, now=now, limit=settings.dispatch_batch_limit)
        db.rollback()  # no transaction is held across Render requests
    summary["eligible"] = len(items)
    task_slug = f"{settings.render_workflow_slug}/{SETTLE_TASK}"
    for item in items:
        key = idempotency_key(item, now)
        try:
            run = client.workflows.start_task(task_slug, {"campaign_id": item.campaign_id}, idempotency_key=key)
        except Exception as error:  # outcome unknown: the same key is reused next tick
            summary["failed"] += 1
            log.warning("dispatch outcome unknown", extra={
                "tp_work_id": item.work_id, "tp_version": item.version, "tp_error": type(error).__name__})
            continue
        run_id = getattr(run, "id", None)
        if not (isinstance(run_id, str) and run_id.startswith("trn-") and hasattr(run, "status")):
            # render==1.8.0's sync start_task returns an Error model (400/401/403/404/429; it
            # also has a string ``id``) or None instead of raising. Only a task run (documented
            # ID format ``trn-...``) is a submission; otherwise the same key is retried next tick.
            summary["failed"] += 1
            log.warning("dispatch rejected", extra={
                "tp_work_id": item.work_id, "tp_version": item.version, "tp_error": type(run).__name__})
            continue
        summary["submitted"] += 1
        summary["runs"].append({"work_id": item.work_id, "campaign_id": item.campaign_id,
                                "version": item.version, "run_id": run_id})
        log.info("dispatched", extra={"tp_work_id": item.work_id, "tp_version": item.version, "tp_run_id": run_id})
    return summary


def main() -> None:  # pragma: no cover - exercised on Render with the installed SDK
    import json
    from render import Render  # official Python SDK client; reads RENDER_API_KEY
    from ..settings import AppSettings

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    settings = AppSettings()
    settings.validate_startup()
    print(json.dumps(dispatch_due(Render(), settings)))


if __name__ == "__main__":  # pragma: no cover
    main()
