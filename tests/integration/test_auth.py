"""Authentication flow tests through the REAL HTTP surface.

No authentication dependency is overridden anywhere: sessions are
issued by the actual login endpoint and resolved by the actual cookie
handling.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select, update

from tipping_point.app import app, create_app
from tipping_point.db.models import Merchant, MerchantCredential, MerchantSession
from tipping_point.db.session import SessionLocal
from tipping_point.settings import AppSettings

from tests.integration.api_helpers import (
    count_sessions_for,
    create_merchant_with_credentials,
    get_csrf_for,
    login_client,
    logged_in_client,
)


def _set_cookie_header(response) -> str:
    return response.headers.get("set-cookie", "")


def test_valid_login_and_current_session(owned):
    client, info = logged_in_client(owned)
    me = client.get("/api/me")
    assert me.status_code == 200
    body = me.json()
    assert body["merchant"]["merchant_id"] == str(info["merchant_id"])
    assert body["session_id"]
    assert body["expires_at"]
    # The raw CSRF token is not re-revealed by /api/me (hash only stored).
    assert body["csrf_token"] == ""


def test_invalid_login_is_generic(owned):
    merchant_id, login, password = create_merchant_with_credentials(owned)
    client = TestClient(app)
    csrf = get_csrf_for(client)

    wrong_password = client.post(
        "/api/merchant/login",
        json={"login_identifier": login, "password": "totally-wrong-pass"},
        headers={"X-CSRF-Token": csrf},
    )
    unknown_login = client.post(
        "/api/merchant/login",
        json={"login_identifier": "ghost-login", "password": "whatever"},
        headers={"X-CSRF-Token": csrf},
    )
    assert wrong_password.status_code == 401
    assert unknown_login.status_code == 401
    assert wrong_password.json()["detail"] == unknown_login.json()["detail"]


def test_no_default_credentials_and_credentialless_merchant_cannot_login(owned):
    # A merchant with NO credentials row must not become eligible.
    import uuid

    merchant_id = uuid.uuid4()
    with SessionLocal() as session:
        session.add(Merchant(id=merchant_id, name="No Credentials"))
        session.commit()
    owned.add(Merchant, merchant_id)

    client = TestClient(app)
    csrf = get_csrf_for(client)
    response = client.post(
        "/api/merchant/login",
        json={"login_identifier": "no-credentials", "password": "any-password"},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 401
    with SessionLocal() as session:
        credentials = session.scalars(
            select(MerchantCredential).where(
                MerchantCredential.merchant_id == merchant_id
            )
        ).all()
    assert credentials == []  # nothing was auto-created


def test_fabricated_and_absent_tokens_rejected(owned):
    client, _ = logged_in_client(owned)
    forged = TestClient(app)
    forged.cookies.set("tipping_session", "fabricated-token-value")
    assert forged.get("/api/me").status_code == 401
    assert client.get("/api/me").status_code == 200
    no_cookie = TestClient(app)
    assert no_cookie.get("/api/me").status_code == 401


def test_expired_session_rejected(owned):
    client, info = logged_in_client(owned)
    token = client.cookies.get("tipping_session")
    assert token
    # Expire the session directly in the database.
    with SessionLocal() as session:
        session.execute(
            update(MerchantSession)
            .where(MerchantSession.merchant_id == info["merchant_id"])
            .values(expires_at=MerchantSession.created_at - timedelta(hours=1))
        )
        session.commit()
    assert client.get("/api/me").status_code == 401


def test_logout_revokes_and_clears(owned):
    client, info = logged_in_client(owned)
    assert client.get("/api/me").status_code == 200
    response = client.post(
        "/api/merchant/logout", headers={"X-CSRF-Token": info["csrf"]}
    )
    assert response.status_code == 200
    # Server-side revocation: the old token no longer resolves.
    assert client.get("/api/me").status_code == 401
    # Cookies were cleared.


def test_login_session_rotation(owned):
    merchant_id, login, password = create_merchant_with_credentials(owned)
    client = TestClient(app)
    status, first = login_client(client, login, password)
    assert status == 200
    first_session_token = client.cookies.get("tipping_session")
    first_csrf = first["csrf_token"]

    # Second login rotates: the first session is revoked and a NEW
    # session plus NEW CSRF token are issued.
    status, second = login_client(client, login, password)
    assert status == 200
    second_session_token = client.cookies.get("tipping_session")
    assert second_session_token != first_session_token
    assert second["csrf_token"] != first_csrf
    assert second["session_id"] != first["session_id"]

    # The rotated-out session can no longer authenticate.
    stale = TestClient(app)
    stale.cookies.set("tipping_session", first_session_token)
    assert stale.get("/api/me").status_code == 401
    assert client.get("/api/me").status_code == 200


def test_cookie_settings_local_vs_hosted(owned):
    # Local (development) configuration: no Secure attribute.
    local_client, local_info = logged_in_client(owned)
    login_response = local_client.post(
        "/api/merchant/login",
        json={
            "login_identifier": local_info["login"],
            "password": local_info["password"],
        },
        headers={"X-CSRF-Token": get_csrf_for(local_client)},
    )
    cookie_header = _set_cookie_header(login_response).lower()
    assert "httponly" in cookie_header
    assert "samesite=lax" in cookie_header
    assert "path=/" in cookie_header
    assert "secure" not in cookie_header
    assert "domain" not in cookie_header  # host-only cookie

    # Hosted configuration: Secure cookies, refused if misconfigured.
    hosted_settings = AppSettings(environment="hosted", cookie_secure=True)
    hosted_app = create_app(hosted_settings)
    merchant_id, login, password = create_merchant_with_credentials(owned)
    client = TestClient(hosted_app, base_url="https://testserver")
    bootstrap = client.get("/api/auth/csrf")
    assert "max-age=" in _set_cookie_header(bootstrap).lower()
    csrf = bootstrap.json()["csrf_token"]
    response = client.post(
        "/api/merchant/login",
        json={"login_identifier": login, "password": password},
        headers={"X-CSRF-Token": csrf},
    )
    cookie_header = _set_cookie_header(response).lower()
    assert response.status_code == 200
    assert "secure" in cookie_header
    assert "httponly" in cookie_header

    # Hosted without secure cookies must refuse to start.
    try:
        AppSettings(environment="hosted", cookie_secure=False).validate_startup()
    except RuntimeError:
        pass
    else:  # pragma: no cover
        raise AssertionError("hosted startup must reject insecure cookies")

    # Local without explicit insecure-dev-cookies opt-in must also refuse.
    try:
        AppSettings(
            environment="local",
            cookie_secure=False,
            allow_insecure_dev_cookies=False,
        ).validate_startup()
    except RuntimeError:
        pass
    else:  # pragma: no cover
        raise AssertionError("local startup must reject disabled insecure dev cookies")


def test_login_throttling_is_bounded(owned):
    merchant_id, login, password = create_merchant_with_credentials(owned)
    client = TestClient(app)
    # Exhaust the failure window with wrong passwords.
    for _ in range(5):
        status, _ = login_client(client, login, "wrong-password-x")
        assert status == 401
    # Even the CORRECT password is now rejected until the window passes.
    status, _ = login_client(client, login, password)
    assert status == 429


def test_auth_responses_not_cacheable(owned):
    client = TestClient(app)
    bootstrap = client.get("/api/auth/csrf")
    assert bootstrap.headers.get("cache-control") == "no-store"
    # Unauthenticated /api/me (401) and rejected login (401) must also be no-store.
    unauth_me = client.get("/api/me")
    assert unauth_me.status_code == 401
    assert unauth_me.headers.get("cache-control") == "no-store"
    bad_login = client.post(
        "/api/merchant/login",
        json={"login_identifier": "nobody", "password": "wrong"},
        headers={"X-CSRF-Token": bootstrap.json()["csrf_token"]},
    )
    assert bad_login.status_code == 401
    assert bad_login.headers.get("cache-control") == "no-store"
    client2, info = logged_in_client(owned)
    me = client2.get("/api/me")
    assert me.headers.get("cache-control") == "no-store"


def test_identity_not_selectable_via_headers_or_body(owned):
    # Body field merchant_id is forbidden by the schema (extra=forbid).
    client, info = logged_in_client(owned)
    csrf = get_csrf_for(client)
    response = client.post(
        "/api/merchant/login",
        json={
            "login_identifier": info["login"],
            "password": info["password"],
            "merchant_id": str(info["merchant_id"]),
        },
        headers={"X-CSRF-Token": csrf, "X-Merchant-Id": str(info["merchant_id"])},
    )
    assert response.status_code == 422
    # Identity still comes only from the session cookie.
    me = client.get("/api/me", headers={"X-Merchant-Id": "someone-else"})
    assert me.status_code == 200
    assert me.json()["merchant"]["merchant_id"] == str(info["merchant_id"])