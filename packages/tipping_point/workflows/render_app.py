"""Render Workflow service entry point: ``python -m tipping_point.workflows.render_app``.

Uses the official Render Python SDK (package ``render``; ``Workflows``,
``TaskContext`` and ``Retry`` imported from ``render`` as in
render-examples/render-workflows-examples-python). Only this module imports
the SDK; task bodies live in ``tasks`` and reuse the existing services.

Retry policy:
- ``settle_campaign`` disables Render-level automatic retries. A failed pass is
  re-dispatched by the cron dispatcher under a fresh idempotency key, and the
  domain claims/ledger decide what, if anything, may run. Financial mutations
  are never blindly replayed by the task runtime.
- ``readiness_diagnostic`` is read-only and may retry.
"""

from __future__ import annotations

import logging

from render import Retry, TaskContext, Workflows

from .tasks import readiness_report, settle_campaign_pass

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

app = Workflows()


@app.task(name="readiness_diagnostic", timeout_seconds=60,
          retry=Retry(max_retries=1, wait_duration_ms=2000, backoff_scaling=1.5))
def readiness_diagnostic(ctx: TaskContext) -> dict:
    return readiness_report()


@app.task(name="settle_campaign", timeout_seconds=300,
          retry=Retry(max_retries=0, wait_duration_ms=1000))
async def settle_campaign(ctx: TaskContext, campaign_id: str) -> dict:
    return await settle_campaign_pass(campaign_id)


if __name__ == "__main__":
    app.start()
