"""Canonical guest session, booking and authorization HTTP contract."""

from contextlib import asynccontextmanager
import hmac
import secrets
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from ..auth.dependencies import get_db
from ..guest.auth import (
    create_guest, ensure_schema, guest_cookie, require_guest, require_guest_csrf,
    resolve_guest, restored_csrf,
)
from ..guest.payments import BookingPaymentService
from ..guest.schemas import BookingOut, EmptyRequest, GuestSessionOut, ReservationRequest
from ..guest.service import BookingService, fail, utcnow
from ..paypal.client import PayPalGateway, PayPalUnconfiguredError
from ..settings import (
    BOOTSTRAP_CSRF_MAX_AGE_SECONDS, GUEST_BOOTSTRAP_COOKIE_NAME,
    GUEST_CSRF_COOKIE_NAME, GUEST_SESSION_COOKIE_NAME,
)
from .schemas import CsrfBootstrap

router = APIRouter(prefix="/api")


@router.get("/guest/csrf", response_model=CsrfBootstrap)
def bootstrap(request: Request, response: Response):
    token = secrets.token_urlsafe(32)
    guest_cookie(response, request.app.state.settings, GUEST_BOOTSTRAP_COOKIE_NAME,
                 token, BOOTSTRAP_CSRF_MAX_AGE_SECONDS)
    return {"csrf_token": token}


@router.post("/guest/session", response_model=GuestSessionOut)
def session_create(body: EmptyRequest, request: Request, response: Response, db=Depends(get_db)):
    cookie = request.cookies.get(GUEST_BOOTSTRAP_COOKIE_NAME, "")
    header = request.headers.get("x-csrf-token", "")
    if not cookie or not header or not hmac.compare_digest(cookie, header):
        fail(403, "CSRF_INVALID", "A valid guest bootstrap CSRF token is required.")
    ensure_schema(db)
    settings = request.app.state.settings
    guest = resolve_guest(db, request.cookies.get(GUEST_SESSION_COOKIE_NAME))
    if guest:
        return {"expires_at": guest.expires_at, "csrf_token": restored_csrf(request, guest)}
    guest, token, csrf = create_guest(db, settings)
    max_age = max(0, int((guest.expires_at - utcnow()).total_seconds()))
    guest_cookie(response, settings, GUEST_SESSION_COOKIE_NAME, token, max_age, httponly=True)
    guest_cookie(response, settings, GUEST_CSRF_COOKIE_NAME, csrf, max_age)
    response.delete_cookie(GUEST_BOOTSTRAP_COOKIE_NAME, path="/", secure=settings.cookie_secure, samesite="lax")
    db.commit()
    return {"expires_at": guest.expires_at, "csrf_token": csrf}


@router.get("/guest/session", response_model=GuestSessionOut)
def session_get(request: Request, guest=Depends(require_guest)):
    return {"expires_at": guest.expires_at, "csrf_token": restored_csrf(request, guest)}


@router.post("/campaigns/{campaign_id}/bookings", status_code=201, response_model=BookingOut)
def reserve(campaign_id: UUID, body: ReservationRequest, request: Request,
            guest=Depends(require_guest_csrf), db=Depends(get_db)):
    service = BookingService(db, request.app.state.settings)
    booking = service.reserve(guest.id, campaign_id, body.email, body.idempotency_key)
    result = service.booking_out(booking)
    db.commit()
    return result


@router.get("/bookings/{booking_id}", response_model=BookingOut)
def status(booking_id: UUID, request: Request, guest=Depends(require_guest), db=Depends(get_db)):
    service = BookingService(db, request.app.state.settings)
    return service.booking_out(service.owned(guest.id, booking_id))


@asynccontextmanager
async def gateway_for(request):
    configured = getattr(request.app.state, "paypal_gateway", None)
    if configured is not None:
        yield configured
        return
    try:
        gateway = PayPalGateway.from_settings(request.app.state.settings)
    except PayPalUnconfiguredError:
        fail(503, "PAYPAL_UNAVAILABLE", "PayPal Sandbox is unavailable.")
    try:
        yield gateway
    finally:
        await gateway.aclose()


async def payment_action(action, booking_id, request, guest, db):
    settings = request.app.state.settings
    service = BookingService(db, settings)
    service.owned(guest.id, booking_id)
    # End ownership-read transaction before constructing/calling the gateway.
    db.commit()
    if action == "cancel":
        payment = BookingPaymentService(db, settings, None)
        booking = await payment.cancel(booking_id)
    else:
        async with gateway_for(request) as gateway:
            payment = BookingPaymentService(db, settings, gateway)
            booking = await getattr(payment, action)(booking_id)
    return service.booking_out(booking)


@router.post("/bookings/{booking_id}/paypal/order", response_model=BookingOut)
async def order(booking_id: UUID, body: EmptyRequest, request: Request,
                guest=Depends(require_guest_csrf), db=Depends(get_db)):
    return await payment_action("create_order", booking_id, request, guest, db)


@router.post("/bookings/{booking_id}/paypal/authorize", response_model=BookingOut)
async def authorize(booking_id: UUID, body: EmptyRequest, request: Request,
                    guest=Depends(require_guest_csrf), db=Depends(get_db)):
    return await payment_action("authorize", booking_id, request, guest, db)


@router.post("/bookings/{booking_id}/cancel", response_model=BookingOut)
async def cancel(booking_id: UUID, body: EmptyRequest, request: Request,
                 guest=Depends(require_guest_csrf), db=Depends(get_db)):
    return await payment_action("cancel", booking_id, request, guest, db)
