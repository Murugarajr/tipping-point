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
- `GET /api/merchant/workshops/{workshop_id}` – Retrieve an owned workshop (returns `404` for unknown or non-owned IDs).
- `PATCH /api/merchant/workshops/{workshop_id}` – Update draft inputs and schedule while unpublished (`409` once published/frozen).
- `POST /api/merchant/workshops/{workshop_id}/preview` – Pure viability calculation over the current draft inputs (no persistence or freeze).
- `POST /api/merchant/workshops/{workshop_id}/publish` – Atomically lock the workshop, revalidate and freeze the draft `CampaignTerms` snapshot, verify costs are coverable at maximum capacity, and create (or idempotently return) the `OPEN` `Campaign`. Note: `OPEN` means published; guest booking and payment capability is not enabled in this slice.

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