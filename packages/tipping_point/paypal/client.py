"""PayPal Sandbox HTTP adapter for authorization-intent checkout.

Verified official contract references (consulted 2026-11-06):
- Authentication (OAuth 2.0 client credentials):
  https://developer.paypal.com/api/rest/authentication/
- Orders v2 overview: https://developer.paypal.com/api/orders/v2/
- Create order: https://developer.paypal.com/api/orders/v2/orders-create/
- Authorize payment for order:
  https://developer.paypal.com/api/orders/v2/orders-authorize
- Payments v2 overview: https://developer.paypal.com/api/payments/v2/
- Void authorized payment:
  https://developer.paypal.com/api/payments/v2/authorizations-void
- Payments OpenAPI schema: https://developer.paypal.com/api/payments/v2/schema.json

Contract decisions verified from those pages:
- The sandbox REST base URL is ``https://api-m.sandbox.paypal.com``.
  The gateway refuses every other base URL, so live mode cannot be
  configured through this class.
- OAuth uses ``POST /v1/oauth2/token`` with HTTP Basic credentials and
  a form-encoded ``grant_type=client_credentials`` body.
- ``PayPal-Request-Id`` is the documented idempotency request header
  for create order, authorize payment for order, and void authorized
  payment, so every mutating call requires an operation-scoped
  ``operation_id`` that retries reuse.
- Voiding returns ``204 No Content`` (or ``200`` with a body).
- ``Prefer: return=representation`` returns full resources for created
  and authorized orders.

Capture/refund operations use the same sandbox transport and operation-scoped
request IDs. Webhook verification remains outside this slice. This adapter
normalizes resources; booking, ownership and settlement policy stay in services.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from time import monotonic
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, quote, urlsplit

import httpx

if TYPE_CHECKING:
    from ..settings import AppSettings

PAYPAL_SANDBOX_HOST = "api-m.sandbox.paypal.com"
PAYPAL_SANDBOX_BASE_URL = f"https://{PAYPAL_SANDBOX_HOST}"
# Hosts PayPal Sandbox uses in *returned* HATEOAS links (observed 2026-11-07:
# refund/capture "up" links on api.sandbox.paypal.com). Parse-only allowlist,
# exact match; it never changes the pinned outbound base URL above.
PAYPAL_SANDBOX_LINK_HOSTS = frozenset({"api.sandbox.paypal.com", PAYPAL_SANDBOX_HOST})
_LINKED_RESOURCE_ID = re.compile(r"[A-Za-z0-9-]{1,100}")
PAYPAL_TOKEN_PATH = "/v1/oauth2/token"
PAYPAL_ORDERS_PATH = "/v2/checkout/orders"
PAYPAL_AUTHORIZATIONS_PATH = "/v2/payments/authorizations"
PAYPAL_INTENT_AUTHORIZE = "AUTHORIZE"
PAYPAL_REQUEST_ID_HEADER = "PayPal-Request-Id"
PAYPAL_PREFER_REPRESENTATION = "return=representation"
PAYPAL_TOKEN_EXPIRY_BUFFER_SECONDS = 60.0
# PayPal currently accepts request IDs up to 10,000 characters. Keep a
# deliberately smaller application policy for durable operation identifiers.
PAYPAL_MAX_REQUEST_ID_LENGTH = 100
PAYPAL_MAX_REFERENCE_ID_LENGTH = 256
PAYPAL_MAX_DESCRIPTION_LENGTH = 127
PAYPAL_MAX_PROVIDER_ISSUES = 5
PAYPAL_CURRENCY_MINOR_EXPONENTS: dict[str, int] = {
    "GBP": 2,
    "EUR": 2,
    "USD": 2,
    "JPY": 0,
}


class PayPalError(RuntimeError):
    """Base sanitized application error for PayPal Sandbox operations."""


class PayPalUnconfiguredError(PayPalError):
    """PayPal Sandbox credentials are not configured on the server."""


class PayPalAuthError(PayPalError):
    """PayPal rejected the sandbox credentials or the bearer token."""


class PayPalTimeoutError(PayPalError):
    """A read-only PayPal Sandbox request timed out (no mutation risk)."""


class PayPalUnavailableError(PayPalError):
    """PayPal Sandbox could not be reached or returned an upstream error."""


class PayPalResponseError(PayPalError):
    """PayPal returned a malformed or unexpected response payload."""


class PayPalRequestError(PayPalError):
    """PayPal definitively rejected an operation.

    ``issues`` carries sanitized provider issue codes only. Provider
    message text is never surfaced because it could echo request data.
    """

    def __init__(self, message: str, *, issues: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.issues = tuple(issues)


class PayPalOutcomeUnknownError(PayPalError):
    """A mutating PayPal call ended without a definitive outcome.

    The mutation may or may not have been applied. Reconcile with the
    provider under the same ``operation_id`` before retrying the same
    logical operation; never silently start a replacement operation.
    """

    def __init__(
        self,
        message: str,
        *,
        operation_id: str | None = None,
        mutation: str = "",
    ) -> None:
        super().__init__(message)
        self.operation_id = operation_id
        self.mutation = mutation


def currency_minor_exponent(currency: str) -> int:
    """Return the minor-unit exponent for a supported currency.

    Unsupported codes are rejected instead of guessed: silent
    wrong-exponent money math is unacceptable.
    """
    if not isinstance(currency, str):
        raise ValueError("currency must be a string")
    normalized = currency.strip().upper()
    if not normalized:
        raise ValueError("currency must be a non-empty code")
    try:
        return PAYPAL_CURRENCY_MINOR_EXPONENTS[normalized]
    except KeyError as exc:
        raise ValueError(f"unsupported currency {normalized!r}") from exc


def format_minor_to_amount(amount_minor: int, currency: str) -> str:
    """Format integer minor units as a PayPal amount ``value`` string.

    Decimal-safe: converts through ``Decimal`` and never through binary
    floating point. ``2500`` pence becomes ``"25.00"``.
    """
    if isinstance(amount_minor, bool) or not isinstance(amount_minor, int):
        raise ValueError("amount_minor must be an integer")
    exponent = currency_minor_exponent(currency)
    amount = Decimal(amount_minor).scaleb(-exponent)
    return f"{amount:f}"


def parse_amount_to_minor(raw_value: object, currency: str) -> int:
    """Convert a PayPal amount value into integer minor units safely.

    Rejects booleans, non-finite values, negatives, non-numeric
    values, and ambiguous fractional minor units.
    """
    if raw_value is None or isinstance(raw_value, bool):
        raise ValueError("missing or non-numeric amount")
    if isinstance(raw_value, float):
        if not math.isfinite(raw_value):
            raise ValueError("non-finite amount")
        raw_str = str(raw_value)
    elif isinstance(raw_value, (int, Decimal)):
        raw_str = str(raw_value)
    elif isinstance(raw_value, str):
        raw_str = raw_value.strip()
        if not raw_str:
            raise ValueError("empty amount")
    else:
        raise ValueError("unsupported amount type")
    try:
        parsed = Decimal(raw_str)
    except InvalidOperation as exc:
        raise ValueError("invalid decimal amount") from exc
    if not parsed.is_finite():
        raise ValueError("non-finite amount")
    if parsed.is_signed() and parsed != 0:
        raise ValueError("negative amount")
    exponent = currency_minor_exponent(currency)
    scaled = parsed.scaleb(exponent)
    integral = scaled.to_integral_exact()
    if scaled != integral:
        raise ValueError("ambiguous fractional minor-unit amount")
    return int(integral)


@dataclass(frozen=True)
class PayPalMoney:
    """A provider money object normalized to integer minor units."""

    amount_minor: int
    currency: str


@dataclass(frozen=True)
class PayPalLink:
    """A sanitized provider HATEOAS link."""

    href: str
    rel: str
    method: str | None


@dataclass(frozen=True)
class PayPalAuthorizationSummary:
    """Authorization reference embedded in an order resource."""

    authorization_id: str
    status: str
    amount_minor: int | None
    currency: str | None


@dataclass(frozen=True)
class PayPalCapture:
    capture_id: str
    status: str
    amount_minor: int | None
    currency: str | None
    authorization_id: str | None
    order_id: str | None
    fee_minor: int | None
    retrieved_at: datetime


@dataclass(frozen=True)
class PayPalRefund:
    refund_id: str
    status: str
    amount_minor: int | None
    currency: str | None
    capture_id: str | None
    retrieved_at: datetime


@dataclass(frozen=True)
class PayPalCaptureSummary:
    """Capture reference embedded in an order resource."""

    capture_id: str
    status: str
    amount_minor: int | None
    currency: str | None


@dataclass(frozen=True)
class PayPalOrder:
    """Sanitized snapshot of an Orders v2 order resource."""

    provider_order_id: str
    status: str
    intent: str | None
    reference_id: str | None
    payee_identifier: str | None
    amount_minor: int | None
    currency: str | None
    approve_url: str | None
    authorizations: tuple[PayPalAuthorizationSummary, ...]
    captures: tuple[PayPalCaptureSummary, ...]
    retrieved_at: datetime
    purchase_unit_count: int = 0
    payee_identifiers: tuple[str, ...] = ()


@dataclass(frozen=True)
class PayPalAuthorization:
    """Sanitized snapshot of a Payments v2 authorization resource."""

    authorization_id: str
    status: str
    order_id: str | None
    amount_minor: int | None
    currency: str | None
    expiration_time: datetime | None
    create_time: datetime | None
    update_time: datetime | None
    seller_protection_status: str | None
    links: tuple[PayPalLink, ...]
    retrieved_at: datetime


@dataclass(frozen=True)
class PayPalVoidResult:
    """Result of voiding an uncaptured authorization."""

    authorization_id: str
    status: str
    retrieved_at: datetime


def _clean_str(value: object) -> str | None:
    """Return a stripped string or ``None`` for missing or blank values."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _parse_links(links: object) -> tuple[PayPalLink, ...]:
    """Extract sanitized HATEOAS links from a provider resource."""
    if not isinstance(links, list):
        return ()
    parsed: list[PayPalLink] = []
    for link in links:
        if not isinstance(link, dict):
            continue
        href = _clean_str(link.get("href"))
        rel = _clean_str(link.get("rel"))
        if href is None or rel is None:
            continue
        parsed.append(
            PayPalLink(href=href, rel=rel, method=_clean_str(link.get("method")))
        )
    return tuple(parsed)


def _parse_iso_datetime(value: object) -> datetime | None:
    """Parse a provider timestamp or surface a response-format error."""
    raw = _clean_str(value)
    if raw is None:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError as exc:
        raise PayPalResponseError("PayPal timestamp was malformed") from exc


def _parse_money(amount: object) -> PayPalMoney | None:
    """Normalize a provider ``amount`` object into safe minor units.

    ``None`` means the resource carried no amount object. Present but
    malformed amounts are response errors, never silent misparses.
    """
    if amount is None:
        return None
    if not isinstance(amount, dict):
        raise PayPalResponseError("PayPal amount was not an object")
    currency = _clean_str(amount.get("currency_code"))
    if currency is None:
        raise PayPalResponseError("PayPal amount was missing currency_code")
    normalized = currency.upper()
    if normalized not in PAYPAL_CURRENCY_MINOR_EXPONENTS:
        raise PayPalResponseError("PayPal amount used an unsupported currency")
    value = amount.get("value")
    if value is None:
        raise PayPalResponseError("PayPal amount was missing value")
    try:
        amount_minor = parse_amount_to_minor(value, normalized)
    except ValueError as exc:
        raise PayPalResponseError("PayPal amount value was malformed") from exc
    return PayPalMoney(amount_minor=amount_minor, currency=normalized)


def _parse_authorization_summary(payload: object) -> PayPalAuthorizationSummary:
    """Normalize a ``payments.authorizations[]`` entry from an order."""
    if not isinstance(payload, dict):
        raise PayPalResponseError("PayPal authorization entry was not an object")
    authorization_id = _clean_str(payload.get("id"))
    if authorization_id is None:
        raise PayPalResponseError("PayPal authorization entry was missing id")
    money = _parse_money(payload.get("amount"))
    return PayPalAuthorizationSummary(
        authorization_id=authorization_id,
        status=_clean_str(payload.get("status")) or "UNKNOWN",
        amount_minor=money.amount_minor if money else None,
        currency=money.currency if money else None,
    )


def _parse_capture_summary(payload: object) -> PayPalCaptureSummary:
    """Normalize a ``payments.captures[]`` entry from an order."""
    if not isinstance(payload, dict):
        raise PayPalResponseError("PayPal capture entry was not an object")
    capture_id = _clean_str(payload.get("id"))
    if capture_id is None:
        raise PayPalResponseError("PayPal capture entry was missing id")
    money = _parse_money(payload.get("amount"))
    return PayPalCaptureSummary(
        capture_id=capture_id,
        status=_clean_str(payload.get("status")) or "UNKNOWN",
        amount_minor=money.amount_minor if money else None,
        currency=money.currency if money else None,
    )


def _embedded_payment_summaries(
    payload: dict[str, object],
) -> tuple[tuple[PayPalAuthorizationSummary, ...], tuple[PayPalCaptureSummary, ...]]:
    """Collect payment resources from top-level and purchase-unit representations.

    Orders v2 normally embeds payment resources under each purchase unit. The
    top-level location is retained for compatibility with sparse/provider test
    representations accepted before embedded resources were modeled.
    """
    payment_objects: list[dict[str, object]] = []
    top_level_payments = payload.get("payments")
    if isinstance(top_level_payments, dict):
        payment_objects.append(top_level_payments)
    purchase_units = payload.get("purchase_units")
    if isinstance(purchase_units, list):
        for unit in purchase_units:
            if isinstance(unit, dict) and isinstance(unit.get("payments"), dict):
                payment_objects.append(unit["payments"])

    authorizations: list[PayPalAuthorizationSummary] = []
    captures: list[PayPalCaptureSummary] = []
    authorization_ids: set[str] = set()
    capture_ids: set[str] = set()
    for payments in payment_objects:
        raw_authorizations = payments.get("authorizations")
        if isinstance(raw_authorizations, list):
            for entry in raw_authorizations:
                authorization = _parse_authorization_summary(entry)
                if authorization.authorization_id not in authorization_ids:
                    authorization_ids.add(authorization.authorization_id)
                    authorizations.append(authorization)
        raw_captures = payments.get("captures")
        if isinstance(raw_captures, list):
            for entry in raw_captures:
                capture = _parse_capture_summary(entry)
                if capture.capture_id not in capture_ids:
                    capture_ids.add(capture.capture_id)
                    captures.append(capture)
    return tuple(authorizations), tuple(captures)


def parse_order(payload: object, *, retrieved_at: datetime | None = None) -> PayPalOrder:
    """Normalize an Orders v2 order resource payload.

    Tolerates sparse payloads (minimal representations) but surfaces
    response errors for structurally malformed resources.
    """
    if not isinstance(payload, dict):
        raise PayPalResponseError("PayPal order response was not an object")
    provider_order_id = _clean_str(payload.get("id"))
    if provider_order_id is None:
        raise PayPalResponseError("PayPal order response was missing id")
    reference_id: str | None = None
    payee_identifier: str | None = None
    payee_identifiers: tuple[str, ...] = ()
    money: PayPalMoney | None = None
    purchase_units = payload.get("purchase_units")
    if isinstance(purchase_units, list) and purchase_units:
        first_unit = purchase_units[0]
        if isinstance(first_unit, dict):
            reference_id = _clean_str(first_unit.get("reference_id"))
            payee = first_unit.get("payee")
            if isinstance(payee, dict):
                payee_identifiers = tuple(
                    value for key in ("merchant_id", "email_address")
                    if (value := _clean_str(payee.get(key))) is not None
                )
                payee_identifier = _clean_str(payee.get("merchant_id")) or _clean_str(
                    payee.get("email_address")
                )
            money = _parse_money(first_unit.get("amount"))
    authorizations, captures = _embedded_payment_summaries(payload)
    approve_url = next(
        (
            link.href
            for link in _parse_links(payload.get("links"))
            if link.rel in ("approve", "payer-action")
        ),
        None,
    )
    return PayPalOrder(
        provider_order_id=provider_order_id,
        status=_clean_str(payload.get("status")) or "UNKNOWN",
        intent=_clean_str(payload.get("intent")),
        reference_id=reference_id,
        payee_identifier=payee_identifier,
        amount_minor=money.amount_minor if money else None,
        currency=money.currency if money else None,
        approve_url=approve_url,
        authorizations=authorizations,
        captures=captures,
        retrieved_at=retrieved_at or datetime.now(timezone.utc),
        purchase_unit_count=len(purchase_units) if isinstance(purchase_units, list) else 0,
        payee_identifiers=payee_identifiers,
    )


def parse_authorization(
    payload: object,
    *,
    retrieved_at: datetime | None = None,
) -> PayPalAuthorization:
    """Normalize a Payments v2 authorization resource payload."""
    if not isinstance(payload, dict):
        raise PayPalResponseError("PayPal authorization response was not an object")
    authorization_id = _clean_str(payload.get("id"))
    if authorization_id is None:
        raise PayPalResponseError("PayPal authorization response was missing id")
    money = _parse_money(payload.get("amount"))
    supplementary_data = payload.get("supplementary_data")
    related_ids = (
        supplementary_data.get("related_ids")
        if isinstance(supplementary_data, dict)
        else None
    )
    order_id = _clean_str(related_ids.get("order_id")) if isinstance(related_ids, dict) else None
    seller_protection = payload.get("seller_protection")
    protection_status = (
        _clean_str(seller_protection.get("status"))
        if isinstance(seller_protection, dict)
        else None
    )
    return PayPalAuthorization(
        authorization_id=authorization_id,
        status=_clean_str(payload.get("status")) or "UNKNOWN",
        order_id=order_id,
        amount_minor=money.amount_minor if money else None,
        currency=money.currency if money else None,
        expiration_time=_parse_iso_datetime(payload.get("expiration_time")),
        create_time=_parse_iso_datetime(payload.get("create_time")),
        update_time=_parse_iso_datetime(payload.get("update_time")),
        seller_protection_status=protection_status,
        links=_parse_links(payload.get("links")),
        retrieved_at=retrieved_at or datetime.now(timezone.utc),
    )


def _related_link_id(link: PayPalLink, collection: str) -> str | None:
    """Parse-only: the identifier named by a trusted Sandbox ``up`` link, else ``None``.

    The URL is never fetched. Outbound requests stay pinned to
    ``PAYPAL_SANDBOX_BASE_URL``; a matching link only names a related
    resource ID that callers must still validate against frozen state.
    """
    if link.rel != "up" or (link.method is not None and link.method != "GET"):
        return None
    try:
        parts = urlsplit(link.href)
        port = parts.port
    except ValueError:
        return None
    if (
        parts.scheme != "https" or parts.netloc not in PAYPAL_SANDBOX_LINK_HOSTS
        or parts.hostname not in PAYPAL_SANDBOX_LINK_HOSTS or port is not None
        or parts.username is not None or parts.password is not None
        or parts.query or parts.fragment or "?" in link.href or "#" in link.href
    ):
        return None
    prefix = f"/v2/payments/{collection}/"
    if not parts.path.startswith(prefix):
        return None
    tail = parts.path[len(prefix):]
    return tail if _LINKED_RESOURCE_ID.fullmatch(tail) else None


def _related_resource(payload, key, collection):
    supplementary = payload.get("supplementary_data")
    related = supplementary.get("related_ids") if isinstance(supplementary, dict) else None
    direct = _clean_str(related.get(key)) if isinstance(related, dict) else None
    links = []
    for link in _parse_links(payload.get("links")):
        linked = _related_link_id(link, collection)
        if linked is not None:
            links.append(linked)
    identifiers = set(links + ([direct] if direct else []))
    if len(identifiers) > 1:
        raise PayPalResponseError("PayPal resource association was contradictory")
    return next(iter(identifiers), None)


def parse_capture(payload, *, retrieved_at=None):
    if not isinstance(payload, dict) or not _clean_str(payload.get("id")):
        raise PayPalResponseError("PayPal capture resource was missing id")
    money = _parse_money(payload.get("amount"))
    breakdown = payload.get("seller_receivable_breakdown")
    fee = _parse_money(breakdown.get("paypal_fee")) if isinstance(breakdown, dict) else None
    if fee and (not money or fee.currency != money.currency):
        raise PayPalResponseError("PayPal fee currency did not match capture")
    supplementary = payload.get("supplementary_data")
    related = supplementary.get("related_ids") if isinstance(supplementary, dict) else None
    return PayPalCapture(
        capture_id=payload["id"].strip(), status=_clean_str(payload.get("status")) or "UNKNOWN",
        amount_minor=money.amount_minor if money else None, currency=money.currency if money else None,
        authorization_id=_related_resource(payload, "authorization_id", "authorizations"),
        order_id=_clean_str(related.get("order_id")) if isinstance(related, dict) else None,
        fee_minor=fee.amount_minor if fee else None, retrieved_at=retrieved_at or datetime.now(timezone.utc),
    )


def parse_refund(payload, *, retrieved_at=None):
    if not isinstance(payload, dict) or not _clean_str(payload.get("id")):
        raise PayPalResponseError("PayPal refund resource was missing id")
    money = _parse_money(payload.get("amount"))
    return PayPalRefund(
        refund_id=payload["id"].strip(), status=_clean_str(payload.get("status")) or "UNKNOWN",
        amount_minor=money.amount_minor if money else None, currency=money.currency if money else None,
        capture_id=_related_resource(payload, "capture_id", "captures"),
        retrieved_at=retrieved_at or datetime.now(timezone.utc),
    )


def build_capture_payload(amount_minor, currency):
    if isinstance(amount_minor, bool) or not isinstance(amount_minor, int) or amount_minor <= 0:
        raise ValueError("capture amount must be a positive integer")
    return {"amount": {"currency_code": currency.strip().upper(), "value": format_minor_to_amount(amount_minor, currency)}, "final_capture": True}


def build_refund_payload(amount_minor, currency):
    body = build_capture_payload(amount_minor, currency)
    return {"amount": body["amount"]}


def build_authorization_order_payload(
    *, reference_id: str, amount_minor: int, currency: str,
    description: str | None = None, expected_payee: str | None = None,
    return_url: str | None = None, cancel_url: str | None = None,
) -> dict:
    """Pure canonical create payload shared by durable operations and gateway."""
    reference = _require_reference_id(reference_id)
    currency_minor_exponent(currency)
    currency = currency.strip().upper()
    if isinstance(amount_minor, bool) or not isinstance(amount_minor, int) or amount_minor <= 0:
        raise ValueError("amount_minor must be a positive integer")
    unit = {
        "reference_id": reference,
        "amount": {"currency_code": currency, "value": format_minor_to_amount(amount_minor, currency)},
    }
    if description is not None:
        description = description.strip()
        if not description or len(description) > PAYPAL_MAX_DESCRIPTION_LENGTH:
            raise ValueError("description must be non-empty and within provider limits")
        unit["description"] = description
    if expected_payee:
        key = "email_address" if "@" in expected_payee else "merchant_id"
        unit["payee"] = {key: expected_payee}
    body = {"intent": PAYPAL_INTENT_AUTHORIZE, "purchase_units": [unit]}
    if return_url is not None or cancel_url is not None:
        if not return_url or not cancel_url:
            raise ValueError("both callback URLs are required")
        body["payment_source"] = {"paypal": {"experience_context": {
            "return_url": return_url, "cancel_url": cancel_url,
            "shipping_preference": "NO_SHIPPING", "user_action": "CONTINUE",
        }}}
    return body


def validate_sandbox_approve_url(url: str | None, order_id: str) -> str:
    """Only expose the provider's exact Sandbox wallet URL for this order."""
    if not url:
        raise ValueError("missing PayPal approval link")
    parts = urlsplit(url)
    if (
        parts.scheme != "https" or parts.netloc != "www.sandbox.paypal.com"
        or parts.username or parts.password or parts.fragment
        or parse_qs(parts.query).get("token") != [order_id]
    ):
        raise ValueError("invalid PayPal Sandbox approval link")
    return url


class PayPalGateway:
    """Async PayPal Sandbox gateway for authorization-intent checkout.

    Scope: sandbox OAuth, AUTHORIZE-intent order creation, order
    retrieval, order authorization, authorization retrieval, and
    voiding an uncaptured authorization. The gateway is sandbox-only:
    the base URL is pinned to the official sandbox host and every
    other URL is refused at construction time. Secrets stay
    server-side: the client secret and bearer token never appear in
    error messages.
    """

    def __init__(
        self,
        *,
        client_id: str | None,
        client_secret: str | None,
        base_url: str = PAYPAL_SANDBOX_BASE_URL,
        timeout_seconds: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = _validate_sandbox_base_url(base_url)
        normalized_id = client_id.strip() if isinstance(client_id, str) else None
        normalized_secret = (
            client_secret.strip() if isinstance(client_secret, str) else None
        )
        if not normalized_id or not normalized_secret:
            raise PayPalUnconfiguredError(
                "PayPal Sandbox credentials are not configured on the server"
            )
        self._client_id = normalized_id
        self._client_secret = normalized_secret
        if timeout_seconds <= 0.0 or timeout_seconds > 30.0:
            raise ValueError("timeout_seconds must be within (0, 30]")
        self._timeout = httpx.Timeout(timeout_seconds)
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
            transport=transport,
        )
        self._token: str | None = None
        self._token_expires_at_monotonic: float = 0.0

    @classmethod
    def from_settings(
        cls,
        settings: AppSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> PayPalGateway:
        """Build a sandbox gateway from application settings.

        Missing credentials refuse construction instead of failing
        lazily on the first payment request.
        """
        if not settings.has_paypal_credentials:
            raise PayPalUnconfiguredError(
                "PayPal Sandbox credentials are not configured on the server"
            )
        assert settings.paypal_client_id is not None
        assert settings.paypal_client_secret is not None
        return cls(
            client_id=settings.paypal_client_id,
            client_secret=settings.paypal_client_secret.get_secret_value(),
            base_url=PAYPAL_SANDBOX_BASE_URL,
            timeout_seconds=settings.paypal_timeout_seconds,
            transport=transport,
        )

    async def _fetch_access_token(self) -> str:
        """Fetch a client-credentials bearer token from the sandbox."""
        try:
            response = await self._client.post(
                PAYPAL_TOKEN_PATH,
                data={"grant_type": "client_credentials"},
                auth=(self._client_id, self._client_secret),
                headers={"Accept": "application/json"},
            )
        except httpx.TimeoutException as exc:
            raise PayPalUnavailableError(
                "PayPal Sandbox token request timed out; check connectivity"
            ) from exc
        except httpx.HTTPError as exc:
            raise PayPalUnavailableError(
                "PayPal Sandbox could not be reached for the token request; "
                "check connectivity"
            ) from exc
        if response.status_code in (400, 401):
            raise PayPalAuthError(
                "PayPal rejected the sandbox credentials; check server configuration"
            )
        if response.status_code != 200:
            raise PayPalUnavailableError(
                f"PayPal Sandbox token endpoint error (HTTP {response.status_code})"
            )
        try:
            payload: object = response.json()
        except ValueError as exc:
            raise PayPalResponseError("PayPal token response was not JSON") from exc
        if not isinstance(payload, dict):
            raise PayPalResponseError("PayPal token response was not an object")
        token = payload.get("access_token")
        if not isinstance(token, str) or not token.strip():
            raise PayPalResponseError("PayPal token response was missing access_token")
        expires_in = payload.get("expires_in")
        if (
            isinstance(expires_in, bool)
            or not isinstance(expires_in, int)
            or expires_in <= 0
        ):
            raise PayPalResponseError("PayPal token response had an invalid expires_in")
        self._token = token.strip()
        self._token_expires_at_monotonic = monotonic() + max(
            0.0, float(expires_in) - PAYPAL_TOKEN_EXPIRY_BUFFER_SECONDS
        )
        return self._token

    async def _access_token(self) -> str:
        """Return a cached bearer token, fetching a fresh one if needed."""
        if self._token is not None and monotonic() < self._token_expires_at_monotonic:
            return self._token
        return await self._fetch_access_token()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        operation_id: str | None = None,
        mutation: str = "",
        prefer_representation: bool = False,
        json_body: object | None = None,
    ) -> httpx.Response:
        """Send one authenticated API request with sanitized transport errors."""
        headers: dict[str, str] = {"Accept": "application/json"}
        if json_body is not None:
            headers["Content-Type"] = "application/json"
        if operation_id is not None:
            headers[PAYPAL_REQUEST_ID_HEADER] = operation_id
        if prefer_representation:
            headers["Prefer"] = PAYPAL_PREFER_REPRESENTATION
        headers["Authorization"] = f"Bearer {await self._access_token()}"
        try:
            response = await self._client.request(
                method, path, json=json_body, headers=headers
            )
        except httpx.TimeoutException as exc:
            raise self._transport_error(
                mutation=mutation,
                operation_id=operation_id,
                reason="the request timed out",
                timeout=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise self._transport_error(
                mutation=mutation,
                operation_id=operation_id,
                reason="PayPal Sandbox could not be reached",
                timeout=False,
            ) from exc
        return response

    @staticmethod
    def _transport_error(
        *,
        mutation: str,
        operation_id: str | None,
        reason: str,
        timeout: bool,
    ) -> PayPalError:
        """Map a transport failure to a definitive or unknown outcome."""
        if not mutation:
            if timeout:
                return PayPalTimeoutError("PayPal Sandbox request timed out")
            return PayPalUnavailableError("PayPal Sandbox service could not be reached")
        return PayPalOutcomeUnknownError(
            f"PayPal {mutation} ended without a definitive outcome ({reason}); "
            "reconcile with the provider before retrying the same operation",
            operation_id=operation_id,
            mutation=mutation,
        )

    def _check_response(
        self,
        response: httpx.Response,
        *,
        mutation: str = "",
        operation_id: str | None = None,
    ) -> None:
        """Raise the sanitized error matching a non-success HTTP status."""
        status = response.status_code
        if 200 <= status < 300:
            return
        if status in (401, 403):
            raise PayPalAuthError(
                "PayPal rejected the request credentials; check server configuration"
            )
        if status in (400, 404, 409, 422):
            raise PayPalRequestError(
                "PayPal rejected the operation",
                issues=_provider_issues(response),
            )
        if mutation:
            raise PayPalOutcomeUnknownError(
                f"PayPal returned HTTP {status} for {mutation}; the outcome is "
                "unknown and must be reconciled before retrying",
                operation_id=operation_id,
                mutation=mutation,
            )
        raise PayPalUnavailableError(f"PayPal Sandbox service error (HTTP {status})")

    def _json_payload(
        self,
        response: httpx.Response,
        *,
        mutation: str = "",
        operation_id: str | None = None,
    ) -> dict[str, object]:
        """Decode a JSON object response, mapping decode errors safely."""
        try:
            payload: object = response.json()
        except ValueError as exc:
            if mutation:
                raise PayPalOutcomeUnknownError(
                    f"PayPal {mutation} returned a non-JSON response; the outcome "
                    "is unknown and must be reconciled before retrying",
                    operation_id=operation_id,
                    mutation=mutation,
                ) from exc
            raise PayPalResponseError("PayPal response was not JSON") from exc
        if not isinstance(payload, dict):
            if mutation:
                raise PayPalOutcomeUnknownError(
                    f"PayPal {mutation} returned a non-object JSON response; the "
                    "outcome is unknown and must be reconciled before retrying",
                    operation_id=operation_id,
                    mutation=mutation,
                )
            raise PayPalResponseError("PayPal response was not a JSON object")
        return payload

    @staticmethod
    def _unknown_from_response_error(
        mutation: str,
        operation_id: str | None,
    ) -> PayPalOutcomeUnknownError:
        """A mutation succeeded HTTP-wise but returned a malformed resource."""
        return PayPalOutcomeUnknownError(
            f"PayPal {mutation} returned a malformed resource; the outcome is "
            "unknown and must be reconciled before retrying",
            operation_id=operation_id,
            mutation=mutation,
        )

    async def create_authorization_order(
        self,
        *,
        reference_id: str,
        amount_minor: int,
        currency: str,
        description: str | None = None,
        operation_id: str,
        retrieved_at: datetime | None = None,
        expected_payee: str | None = None,
        return_url: str | None = None,
        cancel_url: str | None = None,
    ) -> PayPalOrder:
        """Create an AUTHORIZE-intent order for exactly one guest booking.

        ``operation_id`` is the durable logical-operation identifier; it
        is sent as ``PayPal-Request-Id`` so provider-side retries of the
        same logical operation reuse the same idempotency key. The
        returned order is ``CREATED`` and requires buyer approval before
        authorization; admission control stays in the service layer.
        """
        _require_operation_id(operation_id)
        body = build_authorization_order_payload(
            reference_id=reference_id, amount_minor=amount_minor, currency=currency,
            description=description, expected_payee=expected_payee,
            return_url=return_url, cancel_url=cancel_url,
        )
        response = await self._request(
            "POST",
            PAYPAL_ORDERS_PATH,
            operation_id=operation_id,
            mutation="create_authorization_order",
            prefer_representation=True,
            json_body=body,
        )
        self._check_response(
            response,
            mutation="create_authorization_order",
            operation_id=operation_id,
        )
        payload = self._json_payload(
            response,
            mutation="create_authorization_order",
            operation_id=operation_id,
        )
        try:
            return parse_order(payload, retrieved_at=retrieved_at)
        except PayPalResponseError as exc:
            raise self._unknown_from_response_error(
                "create_authorization_order",
                operation_id,
            ) from exc

    async def authorize_order(
        self,
        provider_order_id: str,
        *,
        operation_id: str,
        retrieved_at: datetime | None = None,
    ) -> PayPalOrder:
        """Authorize payment for a buyer-approved order.

        The service layer must confirm buyer approval (order status
        ``APPROVED``) before calling this method. ``operation_id`` is
        sent as ``PayPal-Request-Id`` for idempotent retries.
        """
        _require_operation_id(operation_id)
        order_id = _require_provider_id(provider_order_id, "provider_order_id")
        path = f"{PAYPAL_ORDERS_PATH}/{quote(order_id, safe='')}/authorize"
        response = await self._request(
            "POST",
            path,
            operation_id=operation_id,
            mutation="authorize_order",
            prefer_representation=True,
            json_body={},
        )
        self._check_response(
            response,
            mutation="authorize_order",
            operation_id=operation_id,
        )
        payload = self._json_payload(
            response,
            mutation="authorize_order",
            operation_id=operation_id,
        )
        try:
            return parse_order(payload, retrieved_at=retrieved_at)
        except PayPalResponseError as exc:
            raise self._unknown_from_response_error(
                "authorize_order",
                operation_id,
            ) from exc

    async def get_order(
        self,
        provider_order_id: str,
        *,
        retrieved_at: datetime | None = None,
    ) -> PayPalOrder:
        """Fetch a sanitized snapshot of one order (read-only)."""
        order_id = _require_provider_id(provider_order_id, "provider_order_id")
        path = f"{PAYPAL_ORDERS_PATH}/{quote(order_id, safe='')}"
        response = await self._request("GET", path)
        self._check_response(response)
        payload = self._json_payload(response)
        return parse_order(payload, retrieved_at=retrieved_at)

    async def get_order_response_for_diagnostic(
        self,
        provider_order_id: str,
    ) -> httpx.Response:
        """Fetch one order response for a tightly allowlisted structural diagnostic.

        This is read-only and intentionally returns the checked HTTP response before
        domain normalization. Callers must inspect only an allowlisted diagnostic
        projection and must never log or persist its raw headers or response body.
        """
        order_id = _require_provider_id(provider_order_id, "provider_order_id")
        path = f"{PAYPAL_ORDERS_PATH}/{quote(order_id, safe='')}"
        response = await self._request("GET", path)
        self._check_response(response)
        return response

    async def get_authorization(
        self,
        authorization_id: str,
        *,
        retrieved_at: datetime | None = None,
    ) -> PayPalAuthorization:
        """Fetch a sanitized snapshot of one authorization (read-only)."""
        auth_id = _require_provider_id(authorization_id, "authorization_id")
        path = f"{PAYPAL_AUTHORIZATIONS_PATH}/{quote(auth_id, safe='')}"
        response = await self._request("GET", path)
        self._check_response(response)
        payload = self._json_payload(response)
        return parse_authorization(payload, retrieved_at=retrieved_at)

    async def void_authorization(
        self,
        authorization_id: str,
        *,
        operation_id: str,
        retrieved_at: datetime | None = None,
    ) -> PayPalVoidResult:
        """Void an uncaptured authorization.

        ``operation_id`` is sent as ``PayPal-Request-Id``. The provider
        documents both ``204 No Content`` and ``200`` with a
        representation; both map to a definitive void result. Fully
        captured authorizations cannot be voided.
        """
        _require_operation_id(operation_id)
        auth_id = _require_provider_id(authorization_id, "authorization_id")
        path = f"{PAYPAL_AUTHORIZATIONS_PATH}/{quote(auth_id, safe='')}/void"
        response = await self._request(
            "POST",
            path,
            operation_id=operation_id,
            mutation="void_authorization",
            json_body={},
        )
        self._check_response(
            response,
            mutation="void_authorization",
            operation_id=operation_id,
        )
        fetched_at = retrieved_at or datetime.now(timezone.utc)
        if response.status_code == 204:
            return PayPalVoidResult(
                authorization_id=auth_id,
                status="VOIDED",
                retrieved_at=fetched_at,
            )
        payload = self._json_payload(
            response,
            mutation="void_authorization",
            operation_id=operation_id,
        )
        try:
            authorization = parse_authorization(payload, retrieved_at=fetched_at)
        except PayPalResponseError as exc:
            raise self._unknown_from_response_error(
                "void_authorization",
                operation_id,
            ) from exc
        if authorization.authorization_id != auth_id:
            raise self._unknown_from_response_error("void_authorization", operation_id)
        return PayPalVoidResult(
            authorization_id=auth_id,
            status=authorization.status,
            retrieved_at=fetched_at,
        )

    async def _settlement_mutation(self, path, body, operation_id, parser, mutation):
        """One POST only. Services reconcile unknown outcomes; no automatic replay."""
        _require_operation_id(operation_id)
        response = await self._request(
            "POST", path, operation_id=operation_id, mutation=mutation,
            prefer_representation=True, json_body=body,
        )
        self._check_response(response, mutation=mutation, operation_id=operation_id)
        payload = self._json_payload(response, mutation=mutation, operation_id=operation_id)
        try:
            return parser(payload)
        except PayPalResponseError as exc:
            error = self._unknown_from_response_error(mutation, operation_id)
            # Preserve a discovered reference without retaining sensitive raw payloads.
            resource_id = _clean_str(payload.get("id"))
            if resource_id:
                error.resource_id = resource_id
            raise error from exc

    async def capture_authorization(self, authorization_id, *, amount_minor, currency, operation_id):
        """Payments v2 capture; full approved amount and final_capture=true."""
        auth_id = _require_provider_id(authorization_id, "authorization_id")
        return await self._settlement_mutation(
            f"{PAYPAL_AUTHORIZATIONS_PATH}/{quote(auth_id, safe='')}/capture",
            build_capture_payload(amount_minor, currency), operation_id, parse_capture, "capture_authorization",
        )

    async def get_capture(self, capture_id):
        capture_id = _require_provider_id(capture_id, "capture_id")
        response = await self._request("GET", f"/v2/payments/captures/{quote(capture_id, safe='')}")
        self._check_response(response)
        result = parse_capture(self._json_payload(response))
        if result.capture_id != capture_id:
            raise PayPalResponseError("PayPal returned a different capture")
        return result

    async def refund_capture(self, capture_id, *, amount_minor, currency, operation_id):
        """Refund the exact approved capture amount; completion is a resource state."""
        capture_id = _require_provider_id(capture_id, "capture_id")
        return await self._settlement_mutation(
            f"/v2/payments/captures/{quote(capture_id, safe='')}/refund",
            build_refund_payload(amount_minor, currency), operation_id, parse_refund, "refund_capture",
        )

    async def get_refund(self, refund_id):
        refund_id = _require_provider_id(refund_id, "refund_id")
        response = await self._request("GET", f"/v2/payments/refunds/{quote(refund_id, safe='')}")
        self._check_response(response)
        result = parse_refund(self._json_payload(response))
        if result.refund_id != refund_id:
            raise PayPalResponseError("PayPal returned a different refund")
        return result

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def __aenter__(self) -> PayPalGateway:
        return self

    async def __aexit__(
        self,
        exc_type: object,
        exc: object,
        tb: object,
    ) -> None:
        await self.aclose()


def _provider_issues(response: httpx.Response) -> tuple[str, ...]:
    """Extract sanitized provider issue codes from an error response.

    Only provider ``name`` and ``details[].issue`` codes are kept;
    provider message text is never surfaced because it could echo
    request data.
    """
    try:
        payload: object = response.json()
    except ValueError:
        return ()
    issues: list[str] = []
    if isinstance(payload, dict):
        name = payload.get("name")
        if isinstance(name, str) and name.strip():
            issues.append(name.strip()[:100])
        details = payload.get("details")
        if isinstance(details, list):
            for detail in details:
                if isinstance(detail, dict):
                    issue = detail.get("issue")
                    if isinstance(issue, str) and issue.strip():
                        issues.append(issue.strip()[:100])
                if len(issues) >= PAYPAL_MAX_PROVIDER_ISSUES:
                    break
    return tuple(dict.fromkeys(issues))


def _validate_sandbox_base_url(base_url: object) -> str:
    """Pin the gateway to the official sandbox host; refuse live mode."""
    if not isinstance(base_url, str) or not base_url.strip():
        raise ValueError("base_url must be a non-empty string")
    parts = urlsplit(base_url.strip())
    if parts.scheme != "https" or parts.netloc != PAYPAL_SANDBOX_HOST:
        raise ValueError(
            "base_url must be the PayPal sandbox host "
            f"https://{PAYPAL_SANDBOX_HOST} (sandbox only); "
            "live mode is not supported"
        )
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise ValueError("base_url must be the bare sandbox origin without a path")
    return PAYPAL_SANDBOX_BASE_URL


def _require_operation_id(operation_id: object) -> str:
    """Validate an operation-scoped idempotency identifier."""
    if not isinstance(operation_id, str) or not operation_id.strip():
        raise ValueError(
            "operation_id is required for mutating PayPal operations "
            "(operation-scoped idempotency)"
        )
    cleaned = operation_id.strip()
    if len(cleaned) > PAYPAL_MAX_REQUEST_ID_LENGTH:
        raise ValueError("operation_id exceeds the application request-id length limit")
    return cleaned


def _require_provider_id(value: object, name: str) -> str:
    """Validate a provider-generated resource identifier."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _require_reference_id(reference_id: object) -> str:
    """Validate the client-supplied purchase-unit reference identifier."""
    reference = _require_provider_id(reference_id, "reference_id")
    if len(reference) > PAYPAL_MAX_REFERENCE_ID_LENGTH:
        raise ValueError("reference_id exceeds the provider length limit")
    return reference