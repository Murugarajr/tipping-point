# Tipping Point Scaffold

This repository contains the scaffold for the Tipping Point sandbox workshop booking application.

## Setup

1. **Ensure Python 3.13 is available.** The project requires Python `>=3.13`.

2. **The repository provides a pre‑configured `.venv/` at the root.** Reuse it for all local Python work:

   ```bash
   # Verify the environment
   .venv/bin/python -c "import sys; print('Prefix:', sys.prefix)"

   # Check installed packages
   .venv/bin/python -m pip list
   ```

3. **Install the package with dev extras (for running tests):**

   ```bash
   .venv/bin/python -m pip install -e .[dev]
   ```

4. **Run the offline smoke tests:**

   ```bash
   .venv/bin/python -m pytest
   ```

## Package Structure

- `packages/tipping_point/` – importable FastAPI application package
- `tests/` – offline smoke tests (no external credentials needed)
- `pyproject.toml` – dependency manifest and build configuration
- `requirements.txt` – exact resolved versions (reproducibility artifact)

## Public Frontend

The React/TypeScript/Vite app is in `frontend/`. `/` keeps the approved public
landing page. `/workshops` lists actual published campaigns from the read-only
API, followed by a separate labelled examples area. `/workshops/:workshop-id`
shows deliberately public metadata from the authoritative frozen campaign.
Draft/private IDs return 404 from the public API. `/continue` and `/example-plan`
remain explicit previews: they do not save email, reserve places or authorize
payments. Guest input never grants merchant access.

`/host/login` is sign-in only; successful authentication replaces history with
`/host` or an allowlisted internal return destination. `/host/workshops/new` and
`/host/workshops/:id` provide Basics, Materials, Economics and Review sections.
Saved drafts reopen with complete private inputs and material provenance.
Explicit saves use integer pence converted from validated GBP strings. Reviewed
provider lines are retained by server-validated reference, never caller-supplied
provider facts. Attendance scenarios display the actual returned cost curve,
including non-viable points above the first viable attendance. Publication uses
the existing locking/validation path and makes inputs read-only.

Host sign-in preserves CSRF bootstrap, server-issued session cookies, `/api/me`
and real logout invalidation. Same-host reauthentication retains unsaved inputs
in component memory only; changing merchant resets the mounted editor.
Channel3 searches are explicit actions only, require a budget acknowledgement,
and do not reset any existing request allowance. Offline verification never
calls the live provider.

Use the committed npm lockfile and local frontend tools:

```bash
npm --prefix frontend ci
npm --prefix frontend run dev
npm --prefix frontend run typecheck
npm --prefix frontend test
npm --prefix frontend run build
npm --prefix frontend run test:browser
```

The dependency-free unit tests use Node's experimental TypeScript transform
(verified with Node 24). The browser smoke suite uses installed Chrome and Node's
WebSocket support, starts a temporary production preview on `127.0.0.1:4175`,
and intercepts all API calls with test fixtures. It does not prove live
authentication or provider integration. Set `CHROME_PATH` if Chrome is not at
the default macOS location. Screenshots and isolated browser profiles stay in
ignored `frontend/node_modules/.tmp/frontend-evidence/`; no existing browser
profile is used. No separate lint tool is configured.

Vite development forwards `/api` to the existing backend at port 8000.
Run the backend separately with its documented local cookie/origin configuration
to use real host authentication. Production asset serving under the backend
origin remains a deployment prerequisite; `vite preview` is only a local check.
Server-issued guest sessions, booking ownership/capacity controls, contact
handling, and connected Sandbox checkout/settlement are still required for
genuine bookings. Delivery date, venue, duration and category are not stored by
the current schema and are explicitly unavailable, not fabricated inputs.

Backend integration checks use the existing allowlisted `tipping_point_test`
database and registered test-owned records. The shared fixture checks the
existing schema head without migrating; unavailable or outdated schemas are
reported as skipped. Existing migration-specific tests require a separately
approved scope. A focused migration-free regression command is:

```bash
.venv/bin/python -m pytest tests/unit tests/integration/test_public_workbench.py tests/integration/test_workshop_api.py tests/integration/test_material_api.py tests/integration/test_auth.py tests/integration/test_csrf.py tests/integration/test_concurrent_publish.py -q -rs
```

## API

The minimal FastAPI app provides a single endpoint for health‑checking:

```http
GET /health/live
```

**Response:**

```json
{
  "status": "ok"
}
```

This endpoint requires no external services or credentials and can be used to verify the application is running.

### Merchant Authentication & Workshop APIs

All merchant routes derive identity exclusively from the server-side `tipping_session` cookie (`HttpOnly`, `SameSite=Lax`, `Path=/`, host-only). State-changing requests require the `X-CSRF-Token` header and an allowed `Origin` (when the `Origin` header is present). All `/api/auth/*`, `/api/merchant/login`, `/api/merchant/logout`, and `/api/me` responses set `Cache-Control: no-store`.

- `GET /api/auth/csrf` – Issue an anonymous CSRF bootstrap cookie (`tipping_csrf`) and token for pre-login double-submit.
- `POST /api/merchant/login` – Authenticate (`login_identifier`, `password`), rotate any existing session, and issue a session-bound CSRF token.
- `POST /api/merchant/logout` – Revoke the current session server-side and clear both cookies.
- `GET /api/me` – Return the authenticated merchant and session expiration.
- `POST /api/merchant/workshops` – Create a workshop and initial draft `CampaignTerms` (version 1).
- `GET /api/merchant/workshops` – List workshops owned by the authenticated merchant.
- `GET /api/merchant/workshops/{workshop_id}` – Owner-only full saved financials, schedule, material provenance and persisted campaign, with `Cache-Control: no-store` (`404` for unknown/non-owned IDs).
- `PATCH /api/merchant/workshops/{workshop_id}` – Update draft inputs and schedule while unpublished (`409` once published/frozen).
- `POST /api/merchant/workshops/{workshop_id}/preview` – Pure viability calculation over the current draft inputs (no persistence or freeze).
- `POST /api/merchant/workshops/{workshop_id}/publish` – Atomically lock the workshop, revalidate and freeze the draft `CampaignTerms` snapshot, verify costs are coverable at maximum capacity, and create (or idempotently return) the `OPEN` `Campaign`. Note: `OPEN` means published; guest booking and payment capability is not enabled in this slice.

### Read-only Public Discovery

- `GET /api/workshops` – Up to 100 published workshop projections, newest first.
- `GET /api/workshops/{workshop_id}` – Public detail only when a published campaign references valid frozen terms; otherwise `404`.

Responses allowlist title/description, frozen price/capacity/booking dates,
campaign reference/publication status, and booking-window state. They exclude
merchant identities, private costs/sourcing, credentials, sessions, guest data,
payment resources and raw JSON terms. `reservations_available` is always false
in this slice, including when the published booking window is open.

Draft PATCH material rows can include `selected_offer_snapshot_id` only to
retain an unchanged, already reviewed line in the owned draft. Forged references,
changed provider prices/assumptions and raw `offer_provenance` are rejected.
Use the existing `materials/select` flow to change provider-backed assumptions.


### Channel3 Material Costing

`CHANNEL3_API_KEY` is optional server-side configuration. The backend uses the documented Channel3 REST API through the existing `httpx` dependency; the key is never returned to clients. Search requires an authenticated session, session-bound CSRF token, an allowed Origin, and an owned unpublished workshop. Search uses `POST https://api.trychannel3.com/v1/search` with explicit `config.country=GB`, `config.language=en`, and `config.currency=GBP`.

- `POST /api/merchant/workshops/{workshop_id}/materials/search` accepts a bounded text query and result limit. It stores eligible results as immutable offer snapshots scoped to the merchant and workshop. Invalid/missing prices and non-GBP offers are excluded from costing and reported as rejected. Missing configuration returns `503` with `state=unconfigured`; provider outages/rate limits are reported distinctly.
- `POST /api/merchant/workshops/{workshop_id}/materials/select` accepts only an internal `offer_snapshot_id` plus merchant-reviewed assumptions: product suitability, pack size, shared units, units per attendee, and a shipping allowance in pence with its source. Provider price, currency, merchant, and provenance are always read from the server snapshot. Stale snapshots require a fresh search and explicit review.
- The selected price and reviewed pack/usage assumptions are stored in the campaign financial inputs and passed into the existing deterministic viability calculator. Shipping is a campaign-level allowance counted once. Publication freezes the provider snapshot ID, provider facts, original retrieval timestamp, reviewed assumptions, shipping source, and exact financial inputs; no price refresh occurs at publish time.

Channel3 results are not stock reservations, delivered-cost guarantees, verified pack quantities, or shipping-time promises. Check `GET /api/merchant/workshops/{workshop_id}` / preview; published OPEN campaigns mean published only, not booked or paid. For local HTTP development explicitly set `TIPPING_POINT_ENV=local` and `TIPPING_POINT_ALLOW_INSECURE_DEV_COOKIES=true`; the default is now secure-by-configuration (startup rejects insecure cookies until opted in). See [Channel3 API reference](https://docs.trychannel3.com/api-reference/v1/search.md), [localization](https://docs.trychannel3.com/guides/localization.md), [response fields](https://docs.trychannel3.com/guides/response-overview.md), [offer fields](https://docs.trychannel3.com/guides/offer.md), and [rate limits](https://docs.trychannel3.com/faq/rate-limits.md).

### Provisioning a Merchant Account (Local Operator Command)

No default merchant credentials are ever seeded by migrations or tests. After migrating the target development database, provision a merchant interactively (reads password via hidden `getpass` input and stores only an Argon2id hash):

```bash
.venv/bin/python scripts/provision_merchant.py
```

## Usage for Local Development

```bash
# Start the application
.venv/bin/python -m tipping_point

# Run the tests
.venv/bin/python -m pytest

# Manual check of the health endpoint
curl http://localhost:8000/health/live
```

## Verification Commands

```bash
# Package imports
.venv/bin/python -c "import tipping_point; print(tipping_point.__version__)"

# Liveness endpoint via test client
.venv/bin/python -c "
from fastapi.testclient import TestClient
from tipping_point.app import app
client = TestClient(app)
resp = client.get('/health/live')
print('Status:', resp.status_code)
print('JSON:', resp.json())
"

# Dependency consistency check
.venv/bin/python -m pip check
```

## Dependencies

**Runtime (from `pyproject.toml`):**
- `fastapi` – web framework
- `uvicorn` – ASGI server
- `httpx` – HTTP client
- `pydantic-settings` – configuration management

**Development (from `pyproject.toml[dev]`):**
- `pytest` – test runner

All exact versions are pinned in `requirements.txt` for reproducibility.

## Notes

- The `.venv` directory is ignored by Git and must not be committed.
- No credentials or secrets are required for the health endpoint.
- This scaffold provides the minimal foundation for further implementation of workshop booking, payment integration, and sponsor features.