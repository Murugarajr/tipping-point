"""Guest-only opaque sessions and CSRF; merchant cookies are never read/written."""

from datetime import timedelta
import hmac
import secrets

from fastapi import Depends, Request
from sqlalchemy import select

from ..auth.dependencies import get_db
from ..auth.service import hash_token
from ..db.models import GuestSession
from ..settings import GUEST_CSRF_COOKIE_NAME, GUEST_SESSION_COOKIE_NAME
from .service import fail, guest_schema_available, utcnow


def ensure_schema(db):
    if not guest_schema_available(db):
        fail(503, "RESERVATIONS_UNAVAILABLE", "Guest reservation schema is not installed.")


def resolve_guest(db, token):
    if not token or len(token) > 256:
        return None
    return db.scalar(select(GuestSession).where(
        GuestSession.token_hash == hash_token(token),
        GuestSession.revoked_at.is_(None), GuestSession.expires_at > utcnow(),
    ))


def require_guest(request: Request, db=Depends(get_db)):
    ensure_schema(db)
    guest = resolve_guest(db, request.cookies.get(GUEST_SESSION_COOKIE_NAME))
    if guest is None:
        fail(401, "GUEST_SESSION_REQUIRED", "Your guest session is missing or expired; email cannot restore access.")
    return guest


def require_guest_csrf(request: Request, guest=Depends(require_guest)):
    value = request.headers.get("x-csrf-token", "")
    if not value or not hmac.compare_digest(hash_token(value), guest.csrf_token_hash):
        fail(403, "CSRF_INVALID", "A valid guest CSRF token is required.")
    return guest


def guest_cookie(response, settings, name, value, max_age, *, httponly=False):
    response.set_cookie(name, value, max_age=max_age, secure=settings.cookie_secure,
                        httponly=httponly, samesite="lax", path="/")


def create_guest(db, settings):
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    guest = GuestSession(token_hash=hash_token(token), csrf_token_hash=hash_token(csrf),
                         expires_at=utcnow() + timedelta(hours=settings.guest_session_ttl_hours))
    db.add(guest)
    db.flush()
    return guest, token, csrf


def restored_csrf(request, guest):
    csrf = request.cookies.get(GUEST_CSRF_COOKIE_NAME, "")
    if not csrf or not hmac.compare_digest(hash_token(csrf), guest.csrf_token_hash):
        fail(403, "CSRF_INVALID", "Guest CSRF cookie is unavailable; private access cannot be recovered by email.")
    return csrf
