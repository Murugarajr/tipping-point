# Render deployment and Workflow integration

Status: **prepared in source, SDK installed locally, not deployed.** No Render resource, secret, cloud
database or remote run exists yet. Each step marked *approval* below needs a
separate explicit approval.

## Evidence classes (do not conflate)

| Class | What it proves | Status |
|---|---|---|
| Offline tests | Adapter, dispatcher, gating and recovery logic against real PostgreSQL (`tipping_point_test`), MockTransport PayPal and a fake Render client | Passing locally |
| SDK protocol check (local) | The real `app.start()` of `render==1.8.0` in register and run modes, against a local Unix-socket stub that records what the SDK sends (not Render's local task server) | Passed 2026-11-07 |
| Local workflow execution | Runs through Render's local task server (`render workflows dev`, Render CLI ≥2.35.0) | Not run: Render CLI not installed |
| Remote Render execution | Actual task runs on a deployed Workflow service | Not run |

A completed Render task run means the bounded pass executed. It does **not** mean
a workshop is confirmed; the database (`campaigns.status`, payment operations) is
the only source of truth.

## Official contracts used (verified 2026-11-07)

- SDK: PyPI package `render` (publisher Render, "Python SDK for Render
  Workflows"); Render docs require `render>=1.7.0`. Installed and pinned:
  `render==1.8.0` plus its resolved dependencies in `requirements-render.txt`
  (`httpx==0.28.1` unchanged); declared as the `render` extra in `pyproject.toml`.
- Task definition (render-examples hello-world / file-analyzer):
  `from render import Retry, TaskContext, Workflows`; `app = Workflows()`;
  `@app.task(...)`; tasks take `ctx: TaskContext` first; `app.start()` on startup.
- Decorator options: `name`, `retry=Retry(max_retries, wait_duration_ms, backoff_scaling)`,
  `timeout_seconds` (30–86400), `plan` (default `flex`).
- Triggering: `from render import Render`; `Render()` reads `RENDER_API_KEY`;
  `client.workflows.start_task(task_slug, input_data, *, idempotency_key=None)`;
  task slug `{workflow-slug}/{task-name}`.
- Idempotency keys (SDK ≥1.2.0): enforced 24 h from run creation, scoped to the
  workflow service; a reused key returns the original run. Keys prevent duplicate
  root runs only; tasks must tolerate repeated execution.
- Scheduling: Workflows have no native scheduling; use a cron job. Cron
  schedules are UTC and Render never runs two instances of one cron job at once.
- Blueprint: `type: workflow` services are supported (`runtime: python`,
  `region` required, no `plan`; compute is set per task).
- Worker startup (installed SDK source): `app.start()` reads `RENDER_SDK_MODE`
  (`register` or `run`) and `RENDER_SDK_SOCKET_PATH`, which Render's runtime or
  the local task server provide; it raises if either is missing.
- Task signature: `def task(ctx: TaskContext, <inputs>)` or `async def`; dict
  input is passed as keyword arguments, list input positionally. The SDK
  registers parameters after `ctx` and validates the signature at decoration.
- Local dev: the local task server comes from the Render CLI (≥2.35.0,
  `render workflows dev`, port 8120; CLI task commands need `--local`). The
  Python client targets it with `RENDER_USE_LOCAL_DEV=true` (default URL
  `http://localhost:8120`) or `RENDER_LOCAL_DEV_URL=<url>`; names from the
  installed `render/client/client.py`. The docs page's Node example uses
  `RENDER_TASKS_URL` for direct API use.
- Blueprint schema (https://render.com/schema/render.yaml.json): workflow and
  cron `envVars` accept `fromDatabase`; `fromService.type` includes `workflow`
  and `property: slug` ("Workflow services only. The workflow's slug"). The
  cron job therefore reads the real slug instead of assuming it equals the name.
- Node: Render's default for services created on or after 2026-10-21 is 24.22.1,
  which satisfies Vite 8 (`^20.19.0 || >=22.12.0`). The docs do not say whether
  `NODE_VERSION` applies to Python services, so the web build logs `node --version`.

Docs: https://render.com/docs/workflows, /workflows-sdk-python, /workflows-running,
/workflows-local-development, /workflows-limits, /cronjobs, /blueprint-spec,
https://github.com/render-examples/render-workflows-examples-python

## Code map

| Path | Role |
|---|---|
| `packages/tipping_point/workflows/tasks.py` | SDK-free task bodies: `settle_campaign_pass(campaign_id)` (one bounded `process_due(limit=1, campaign_id=…)` pass) and `readiness_report()` |
| `packages/tipping_point/workflows/render_app.py` | Render Workflow entry point; registers `settle_campaign` (no Render-level retries) and `readiness_diagnostic` |
| `packages/tipping_point/workflows/dispatcher.py` | Cron entry point; read-only selection of due non-cleanup work, `start_task` with deterministic idempotency keys |
| `packages/tipping_point/app.py` | `/health/live` (Render deploy health check: process liveness only) and `/health/ready` (database and schema; 503 until migrated, checked manually); opt-in same-origin SPA serving (`TIPPING_POINT_SERVE_FRONTEND`) |
| `packages/tipping_point/db/config.py` | `TIPPING_POINT_DATABASE_URL` (PostgreSQL only) |
| `render.yaml`, `.python-version`, `requirements-render.txt` | Deployment configuration |

### Safety properties

- Task input is exactly one canonical campaign UUID. No credentials, buyer data,
  amounts or provider operations are ever task arguments.
- `TIPPING_POINT_REMOTE_SETTLEMENT_MODE` defaults to `disabled`. Both the
  dispatcher and the task enforce it server-side; `campaign_allowlist` limits
  execution to exact campaign UUIDs.
- `OPERATOR_TEST_CLEANUP` work is never selected or claimed by the dispatcher or task.
- No database transaction is held across Render or PayPal requests.
- At-least-once delivery: duplicates, lost responses, early starts and crashed
  workers are absorbed by work claims/leases/version fencing, durable operation
  request IDs and retrieval-only reconciliation. Execution is never "exactly once".
- Known limitation: dispatch run IDs are logged, not persisted. Persisting them
  would need a schema change (separate proposal).

## Proposed resource topology and cost considerations

| Resource | Blueprint name | Plan in `render.yaml` | Notes |
|---|---|---|---|
| Postgres | `tipping-point-db` | `0.1c-256mb` | Paid, non-expiring. Free Postgres expires after 30 days, which does not cover judging. `ipAllowList: []` (private network only) |
| Web service | `tipping-point-web` | `0.5c-512mb` | FastAPI and built React on one HTTPS origin |
| Workflow service | `tipping-point-workflows` | per task (`flex`) | $0.20/CPU-hour and $0.05/GB-hour, billed per second; argument/result retention $0.25/GB-month |
| Cron job | `tipping-point-dispatcher` | `0.5c-512mb`, every minute | Billed by running time, with a $1/month minimum per cron job |

All services are in one region (`frankfurt`) so they share the private network.
Confirm current web and Postgres prices in the Render dashboard before
provisioning; this document does not quote them. Hobby workspaces allow 50
root-level run API requests per minute; `TIPPING_POINT_DISPATCH_BATCH_LIMIT`
(default 10) keeps the dispatcher under that.

## Environment variables (names only)

| Name | Web | Workflow | Cron | Secret |
|---|---|---|---|---|
| `TIPPING_POINT_DATABASE_URL` (from database) | ✓ | ✓ | ✓ | managed by Render |
| `TIPPING_POINT_ENV=hosted`, `TIPPING_POINT_COOKIE_SECURE=true` | ✓ | ✓ | ✓ | no |
| `TIPPING_POINT_ALLOW_INSECURE_DEV_COOKIES=false`, `TIPPING_POINT_SERVE_FRONTEND=true` | ✓ | | | no |
| `APP_PUBLIC_URL` (exact HTTPS origin; always an allowed origin) | ✓ | | | no (set at creation) |
| `TIPPING_POINT_ALLOWED_ORIGINS=""` (no extra origins; replaces localhost defaults) | ✓ | | | no |
| `PAYPAL_ENV=sandbox` | ✓ | ✓ | | no |
| `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_EXPECTED_PAYEE` | ✓ | ✓ | | yes |
| `CHANNEL3_API_KEY` | ✓ | | | yes |
| `TIPPING_POINT_REMOTE_SETTLEMENT_MODE` (default `disabled`) | ✓ | ✓ | ✓ | no |
| `TIPPING_POINT_REMOTE_SETTLEMENT_CAMPAIGN_IDS` | | ✓ | ✓ | no |
| `TIPPING_POINT_RENDER_WORKFLOW_SLUG` | | | ✓ | no |
| `RENDER_API_KEY` | | | ✓ | yes |

Hosted startup refuses: non-HTTPS public origin, insecure cookies, `allow_insecure_dev_cookies` in hosted mode,
`campaign_allowlist` without campaigns, and any non-Sandbox PayPal mode (not
representable in settings). PayPal return/cancel callbacks derive from
`APP_PUBLIC_URL`; guest reservations stay unavailable until it is a valid HTTPS
origin and the Sandbox payee is configured.

## Deployment steps (each needs approval)

1. Done 2026-11-07: `render==1.8.0` installed and pinned; registration test and
   SDK protocol check passed. Optional, *approval*: install the Render CLI
   (≥2.35.0) for a run through Render's own local task server.
2. *Approval:* push the `render` branch (or a merge) so Render can build it.
3. *Approval:* create the Blueprint resources (paid Postgres, web, workflow,
   cron) and enter the `sync: false` secrets in the dashboard.
4. *Approval:* migrate the empty cloud database from a Render Shell:
   `python -m alembic upgrade head`; confirm `/health/ready` returns `ready`.
5. *Approval:* provision a hosted merchant credential (existing
   `scripts/provision_merchant.py`), never committed.
6. First remote task (below). Remote financial execution stays `disabled`.
7. *Separate approval:* campaign-scoped remote settlement test (below).

## First harmless remote task

With `TIPPING_POINT_REMOTE_SETTLEMENT_MODE=disabled` everywhere:

1. Trigger `tipping-point-workflows/readiness_diagnostic` once from the
   dashboard or CLI (no input).
2. Expect booleans and versions only: `database_reachable`,
   `schema_revision_matches`, `settlement_schema_present`,
   `paypal_sandbox_credentials_present`,
   `remote_financial_execution_enabled=false`, `financial_operations_performed=0`,
   `git_commit` matching the deployed commit.
3. Optionally trigger `settle_campaign` with a random UUID and confirm it returns
   `financial_execution: refused`, `REMOTE_SETTLEMENT_DISABLED`.
4. Let the cron dispatcher run and confirm it logs `dispatch skipped: remote
   settlement disabled`.

Record the task run IDs as evidence. This proves only that the Workflow service
runs our code; it is **not** settlement integration.

## Campaign-scoped remote settlement test (separately approved)

1. Publish a fresh GBP 1.00, capacity-1 Sandbox workshop on the hosted app with
   the local Sandbox preset equivalent (short window); reserve and authorize one place.
2. Set `TIPPING_POINT_REMOTE_SETTLEMENT_MODE=campaign_allowlist` and
   `TIPPING_POINT_REMOTE_SETTLEMENT_CAMPAIGN_IDS=<that campaign UUID>` on the
   workflow and cron services only.
3. After cutoff, the cron dispatcher submits `settle_campaign`; record the run IDs.
4. Verify from the database (not the run status): decision `COLLECT`, exactly
   one capture operation, campaign `CONFIRMED`, work `DONE`.
5. Return both services to `disabled`. Any refund cleanup uses the existing
   operator path under its own approval.
