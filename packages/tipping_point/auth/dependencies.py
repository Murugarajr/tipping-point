"""FastAPI dependencies for authentication, CSRF, and request sessions.

CSRF pattern (documented choice — synchronizer token with server-side
storage, plus a double-submit bootstrap for the pre-login request):

- ``GET /api/auth/csrf`` issues an anonymous CSRF token cookie
  (non-HttpOnly so browser JavaScript can echo it). The login request
  must echo that value in the ``X-CSRF-Token`` header (double-submit
  for the anonymous phase only).
- On successful login the server issues a NEW CSRF token whose hash is
  stored on the created session row; every authenticated mutation must
  echo it and the server compares hashes against the session's
  ``csrf_token_hash``. Session rotation therefore invalidates the old
  CSRF token together with the old session.

Merchant identity comes ONLY from the session cookie resolved
server-side. Request headers and body fields never select identity or
role. Secret comparisons use ``hmac.compare_digest`` from the standard
library; no custom cryptography exists anywhere.
"""

from __future__ import annotations

import hmac
import secrets
from dataclasses import dataclass
from typing import Iterator

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..db.models import Merchant, MerchantSession
from ..db.session import SessionLocal
from ..settings import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME
from .service import MerchantAuthService, hash_token


def get_db() -> Iterator[Session]:
    """One transactional session per request; commit on success."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except HTTPException:
        session.rollback()
        raise
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _auth_service(request: Request, session: Session) -> MerchantAuthService:
    settings = request.app.state.settings
    return MerchantAuthService(
        session,
        ttl_hours=settings.session_ttl_hours,
        max_failures=settings.throttle_max_failures,
        window_minutes=settings.throttle_window_minutes,
    )


@dataclass(frozen=True)
class AuthContext:
    merchant: Merchant
    session_row: MerchantSession


def get_auth_context(
    request: Request, session: Session = Depends(get_db)
) -> AuthContext:
    """Dependency: an active session cookie, else 401."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="authentication required")
    resolved = _auth_service(request, session).resolve_session(token)
    if resolved is None:
        raise HTTPException(status_code=401, detail="authentication required")
    row, merchant = resolved
    return AuthContext(merchant=merchant, session_row=row)


def require_csrf(request: Request, auth: AuthContext) -> None:
    """Dependency for authenticated mutations: session-bound CSRF token."""
    presented = request.headers.get("x-csrf-token", "")
    if not presented:
        raise HTTPException(status_code=403, detail="missing CSRF token")
    if not hmac.compare_digest(
        hash_token(presented), auth.session_row.csrf_token_hash
    ):
        raise HTTPException(status_code=403, detail="invalid CSRF token")


def require_login_csrf(request: Request) -> None:
    """Pre-login CSRF: the header must echo the anonymous CSRF cookie."""
    cookie_value = request.cookies.get(CSRF_COOKIE_NAME, "")
    header_value = request.headers.get("x-csrf-token", "")
    if not cookie_value or not header_value:
        raise HTTPException(status_code=403, detail="missing CSRF token")
    if not hmac.compare_digest(cookie_value, header_value):
        raise HTTPException(status_code=403, detail="invalid CSRF token")


def new_anonymous_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def session_token_from(request: Request) -> str | None:
    return request.cookies.get(SESSION_COOKIE_NAME)