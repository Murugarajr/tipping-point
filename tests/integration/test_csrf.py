"""CSRF and Origin validation tests across state-changing endpoints.

Verifies the documented CSRF pattern:
- Pre-login double-submit via GET /api/auth/csrf + X-CSRF-Token header.
- Post-login session-bound synchronizer token (SHA-256 hash stored on
  the session row); session rotation invalidates the previous CSRF
  token.
- Origin header validation for state-changing requests; no wildcard
  credentialed CORS.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tipping_point.app import app

from tests.integration.api_helpers import (
    create_merchant_with_credentials,
    get_csrf_for,
    login_client,
    logged_in_client,
    viable_workshop_body as _viable_workshop_body,
)


def test_login_requires_csrf_bootstrap(owned):
    _, login, password = create_merchant_with_credentials(owned)
    client = TestClient(app)
    # No bootstrap cookie and no header -> 403.
    missing = client.post(
        "/api/merchant/login",
        json={"login_identifier": login, "password": password},
    )
    assert missing.status_code == 403

    # Bootstrap cookie present, mismatched header -> 403.
    csrf = get_csrf_for(client)
    mismatched = client.post(
        "/api/merchant/login",
        json={"login_identifier": login, "password": password},
        headers={"X-CSRF-Token": csrf + "-tampered"},
    )
    assert mismatched.status_code == 403


def test_mutations_reject_missing_or_invalid_csrf(owned):
    client, info = logged_in_client(owned)
    body = _viable_workshop_body()

    # Missing CSRF header on workshop creation -> 403.
    no_csrf = client.post("/api/merchant/workshops", json=body)
    assert no_csrf.status_code == 403

    # Wrong CSRF token -> 403.
    bad_csrf = client.post(
        "/api/merchant/workshops",
        json=body,
        headers={"X-CSRF-Token": "wrong-csrf-token"},
    )
    assert bad_csrf.status_code == 403

    # Missing CSRF on logout -> 403; session stays valid.
    bad_logout = client.post("/api/merchant/logout")
    assert bad_logout.status_code == 403
    assert client.get("/api/me").status_code == 200


def test_session_rotation_invalidates_prior_csrf_token(owned):
    _, login, password = create_merchant_with_credentials(owned)
    client = TestClient(app)
    status, first = login_client(client, login, password)
    assert status == 200
    old_csrf = first["csrf_token"]

    # Rotate by logging in again.
    status, second = login_client(client, login, password)
    assert status == 200
    new_csrf = second["csrf_token"]
    assert new_csrf != old_csrf

    # Old CSRF token must be rejected on the new session.
    rejected = client.post(
        "/api/merchant/workshops",
        json=_viable_workshop_body(),
        headers={"X-CSRF-Token": old_csrf},
    )
    assert rejected.status_code == 403


def test_disallowed_origin_rejected_and_allowed_origin_accepted(owned):
    client, info = logged_in_client(owned)
    body = _viable_workshop_body()

    # Cross-origin mutation from an unlisted origin -> 403.
    evil = client.post(
        "/api/merchant/workshops",
        json=body,
        headers={
            "X-CSRF-Token": info["csrf"],
            "Origin": "https://attacker.example",
        },
    )
    assert evil.status_code == 403
    # No wildcard credentialed CORS headers are ever emitted.
    assert evil.headers.get("access-control-allow-origin") is None

    # Configured local origin + valid CSRF -> 201.
    allowed = client.post(
        "/api/merchant/workshops",
        json=body,
        headers={
            "X-CSRF-Token": info["csrf"],
            "Origin": "http://localhost:5173",
        },
    )
    assert allowed.status_code == 201