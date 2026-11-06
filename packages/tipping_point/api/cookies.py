"""Cookie helpers for merchant sessions.

Cookie policy (explicit, documented): the session cookie is HttpOnly;
the CSRF cookie is deliberately NOT HttpOnly so browser JavaScript
can echo it in a header. Both use SameSite=Lax, Path=/, and the
configured Secure flag, with Max-Age matching the session TTL. No
Domain attribute is ever set (host-only cookies). Local plain-HTTP
cookies are permitted only under explicit development configuration;
hosted environments must set TIPPING_POINT_COOKIE_SECURE=true or the
application refuses to start.
"""

from __future__ import annotations

from fastapi import Response

from ..auth.service import MerchantAuthService
from ..db.models import MerchantSession
from ..settings import AppSettings, CSRF_COOKIE_NAME, SESSION_COOKIE_NAME


def auth_service_for(request, session) -> MerchantAuthService:
    settings = request.app.state.settings
    return MerchantAuthService(
        session,
        ttl_hours=settings.session_ttl_hours,
        max_failures=settings.throttle_max_failures,
        window_minutes=settings.throttle_window_minutes,
    )


def set_session_cookies(
    response: Response,
    session_token: str,
    csrf_token: str,
    settings: AppSettings,
    row: MerchantSession,
) -> None:
    max_age = int((row.expires_at - row.created_at).total_seconds())
    response.set_cookie(
        SESSION_COOKIE_NAME,
        session_token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        path="/",
        secure=settings.cookie_secure,
    )
    response.set_cookie(
        CSRF_COOKIE_NAME,
        csrf_token,
        max_age=max_age,
        httponly=False,
        samesite="lax",
        path="/",
        secure=settings.cookie_secure,
    )


def clear_session_cookies(response: Response, settings: AppSettings) -> None:
    for name, httponly in ((SESSION_COOKIE_NAME, True), (CSRF_COOKIE_NAME, False)):
        response.set_cookie(
            name,
            "",
            max_age=0,
            expires=0,
            httponly=httponly,
            samesite="lax",
            path="/",
            secure=settings.cookie_secure,
        )