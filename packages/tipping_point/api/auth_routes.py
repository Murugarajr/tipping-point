"""Authentication routes: login, logout, current session, CSRF bootstrap.

All auth responses carry Cache-Control: no-store. Merchant identity is
resolved exclusively from the session cookie — never from headers or
body fields. Rejections are generic.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from ..auth.dependencies import (
    get_auth_context,
    get_db,
    new_anonymous_csrf_token,
    require_csrf,
    require_login_csrf,
    session_token_from,
    AuthContext,
)
from ..auth.service import LoginRejected, LoginThrottled
from ..settings import BOOTSTRAP_CSRF_MAX_AGE_SECONDS, CSRF_COOKIE_NAME
from .cookies import auth_service_for, clear_session_cookies, set_session_cookies
from .schemas import CsrfBootstrap, LoginRequest, MerchantInfo, SessionInfo

router = APIRouter()


def _no_store(response: Response) -> Response:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return response


@router.get("/api/auth/csrf")
def csrf_bootstrap(request: Request, response: Response) -> CsrfBootstrap:
    """Issue an anonymous CSRF token cookie for the login request."""
    settings = request.app.state.settings
    token = new_anonymous_csrf_token()
    response.set_cookie(
        CSRF_COOKIE_NAME,
        token,
        max_age=BOOTSTRAP_CSRF_MAX_AGE_SECONDS,
        httponly=False,  # browser JavaScript must echo it in a header
        samesite="lax",
        path="/",
        secure=settings.cookie_secure,
    )
    _no_store(response)
    return CsrfBootstrap(csrf_token=token)


@router.post("/api/merchant/login")
def login(
    request: Request,
    response: Response,
    payload: LoginRequest,
    db: Session = Depends(get_db),
) -> SessionInfo:
    """Authenticate and issue a rotated session with bound CSRF token."""
    require_login_csrf(request)
    service = auth_service_for(request, db)
    try:
        merchant, row, session_token, csrf_token = service.login(
            payload.login_identifier,
            payload.password,
            rotate_session_token=session_token_from(request),
        )
    except LoginThrottled:
        raise HTTPException(
            status_code=429, detail="too many failed attempts"
        ) from None
    except LoginRejected:
        # Generic message; never reveal which part failed.
        raise HTTPException(
            status_code=401, detail="invalid login credentials"
        ) from None

    set_session_cookies(response, session_token, csrf_token, request.app.state.settings, row)
    _no_store(response)
    return SessionInfo(
        merchant=MerchantInfo(merchant_id=str(merchant.id), name=merchant.name),
        session_id=str(row.id),
        expires_at=row.expires_at,
        csrf_token=csrf_token,
    )


@router.post("/api/merchant/logout")
def logout(
    request: Request,
    response: Response,
    auth: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    """Revoke the session server-side and clear both cookies."""
    require_csrf(request, auth)
    token = session_token_from(request)
    assert token is not None  # get_auth_context guarantees presence
    auth_service_for(request, db).logout(token)
    clear_session_cookies(response, request.app.state.settings)
    _no_store(response)
    return {"status": "logged out"}


@router.get("/api/me")
def me(
    response: Response,
    auth: AuthContext = Depends(get_auth_context),
) -> SessionInfo:
    """Current merchant/session and permitted capabilities.

    The raw CSRF token is not re-revealed here (only its hash is
    stored); it is delivered at login.
    """
    _no_store(response)
    return SessionInfo(
        merchant=MerchantInfo(
            merchant_id=str(auth.merchant.id), name=auth.merchant.name
        ),
        session_id=str(auth.session_row.id),
        expires_at=auth.session_row.expires_at,
        csrf_token="",
    )