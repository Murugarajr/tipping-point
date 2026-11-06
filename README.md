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