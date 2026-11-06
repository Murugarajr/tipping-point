"""Channel3 HTTP API adapter for GB/en/GBP material offer discovery.

Verified official contract references:
- Search API Reference (OpenAPI 3.1.0): https://docs.trychannel3.com/api-reference/v1/search.md
- OpenAPI Specification: https://docs.trychannel3.com/openapi/openapi.json
- Localization Guide: https://docs.trychannel3.com/guides/localization.md
- Search Response Overview: https://docs.trychannel3.com/guides/response-overview.md
- Offer Guide: https://docs.trychannel3.com/guides/offer.md
- Rate Limits FAQ: https://docs.trychannel3.com/faq/rate-limits.md
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Callable
from urllib.parse import urlsplit

import httpx

CHANNEL3_COUNTRY = "GB"
CHANNEL3_LANGUAGE = "en"
CHANNEL3_CURRENCY = "GBP"
CHANNEL3_MAX_QUERY_LENGTH = 200
CHANNEL3_MAX_LIMIT = 20
CHANNEL3_MAX_OFFERS = 40
CHANNEL3_DEFAULT_LIMIT = 10
CHANNEL3_MAX_RETRY_AFTER_SECONDS = 5.0


class Channel3Error(RuntimeError):
    """Base sanitized application error for Channel3 operations."""


class Channel3UnconfiguredError(Channel3Error):
    """CHANNEL3_API_KEY is not configured on the server."""


class Channel3AuthError(Channel3Error):
    """Channel3 rejected the server API key or reported exhausted credits."""


class Channel3RateLimitError(Channel3Error):
    """Channel3 returned 429 Too Many Requests."""

    def __init__(self, message: str, *, retry_after_seconds: int | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class Channel3TimeoutError(Channel3Error):
    """Channel3 search request timed out."""


class Channel3UnavailableError(Channel3Error):
    """Channel3 is temporarily unavailable or returned an upstream error."""


class Channel3ResponseError(Channel3Error):
    """Channel3 returned a malformed response payload."""


@dataclass(frozen=True)
class NormalizedOfferCandidate:
    """Normalized product offer returned by Channel3 search."""

    provider_product_id: str | None
    provider_offer_ref: str
    product_title: str
    brand_name: str | None
    merchant_domain: str
    reported_price_raw: str | None
    price_minor: int | None
    currency: str | None
    product_url: str | None
    image_url: str | None
    availability: str | None
    condition: str | None
    locale_country: str
    locale_language: str
    locale_currency: str
    retrieved_at: datetime
    costing_eligible: bool
    ineligible_reason: str | None = None


@dataclass(frozen=True)
class Channel3SearchResult:
    """Sanitized result of a single Channel3 search."""

    query: str
    locale_country: str
    locale_language: str
    locale_currency: str
    retrieved_at: datetime
    offers: list[NormalizedOfferCandidate] = field(default_factory=list)
    eligible_count: int = 0
    rejected_count: int = 0
    next_page_token: str | None = None


def parse_major_to_pence(raw_value: object) -> tuple[int, str]:
    """Convert a provider major-unit GBP price into integer pence safely.

    Rejects booleans, NaN/Infinity, negative or zero prices, non-numeric
    values, and ambiguous fractional pence (more than two decimal places).
    Never uses binary floating-point arithmetic for the conversion.
    """
    if raw_value is None or isinstance(raw_value, bool):
        raise ValueError("missing or non-numeric price")
    if isinstance(raw_value, float):
        if not math.isfinite(raw_value):
            raise ValueError("non-finite price")
        raw_str = str(raw_value)
    elif isinstance(raw_value, (int, Decimal)):
        raw_str = str(raw_value)
    elif isinstance(raw_value, str):
        raw_str = raw_value.strip()
        if not raw_str:
            raise ValueError("empty price")
    else:
        raise ValueError("unsupported price type")

    try:
        dec = Decimal(raw_str)
    except InvalidOperation as exc:
        raise ValueError("invalid decimal price") from exc

    if not dec.is_finite():
        raise ValueError("non-finite decimal price")
    if dec <= 0:
        raise ValueError("price must be strictly positive")

    scaled = dec * Decimal(100)
    integral = scaled.to_integral_exact()
    if scaled != integral:
        raise ValueError(
            "ambiguous sub-penny price precision (more than 2 decimal places)"
        )
    pence = int(integral)
    if pence <= 0:
        raise ValueError("price in pence must be strictly positive")
    normalized_raw = f"{dec.quantize(Decimal('0.01'))}"
    return pence, normalized_raw



def _extract_image_url(images: object) -> str | None:
    if not isinstance(images, list) or not images:
        return None
    dict_images = [img for img in images if isinstance(img, dict)]
    if not dict_images:
        return None
    chosen = next(
        (img for img in dict_images if img.get("is_main_image") is True),
        dict_images[0],
    )
    cleaned = chosen.get("cleaned_url")
    if isinstance(cleaned, str) and cleaned.strip():
        return cleaned.strip()
    url = chosen.get("url")
    if isinstance(url, str) and url.strip():
        return url.strip()
    return None


def _extract_brand_name(brands: object) -> str | None:
    if not isinstance(brands, list) or not brands:
        return None
    first = brands[0]
    if isinstance(first, dict):
        name = first.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None


def _build_offer_ref(
    product_id: str | None,
    domain: str,
    url: str | None,
    index: int,
) -> str:
    seed = f"{product_id or 'unknown'}|{domain}|{url or index}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    if product_id:
        return f"{product_id}:{domain}:{digest}"
    return f"{domain}:{digest}"


def _parse_retry_after(header_val: str | None) -> int | None:
    if not header_val:
        return None
    try:
        parsed = int(header_val.strip())
    except ValueError:
        return None
    return max(0, parsed)



def normalize_search_payload(
    payload: object,
    *,
    query: str,
    retrieved_at: datetime | None = None,
) -> Channel3SearchResult:
    """Normalize a Channel3 ``SearchResponse`` payload into offer candidates."""
    if not isinstance(payload, dict) or not isinstance(payload.get("products"), list):
        raise Channel3ResponseError(
            "Channel3 response did not contain a valid products list"
        )

    fetched_at = retrieved_at or datetime.now(timezone.utc)
    candidates: list[NormalizedOfferCandidate] = []
    eligible = 0
    rejected = 0

    for product in payload["products"]:
        if len(candidates) >= CHANNEL3_MAX_OFFERS:
            break
        if not isinstance(product, dict):
            continue
        raw_pid = product.get("id")
        product_id = (
            raw_pid.strip()
            if isinstance(raw_pid, str) and raw_pid.strip()
            else None
        )
        raw_title = product.get("title")
        title = (
            raw_title.strip()
            if isinstance(raw_title, str) and raw_title.strip()
            else ""
        )
        brand_name = _extract_brand_name(product.get("brands"))
        image_url = _extract_image_url(product.get("images"))
        offers = product.get("offers")
        if not isinstance(offers, list):
            continue

        for idx, offer in enumerate(offers):
            if len(candidates) >= CHANNEL3_MAX_OFFERS:
                break
            if not isinstance(offer, dict):
                continue
            raw_domain = offer.get("domain")
            domain = (
                raw_domain.strip()
                if isinstance(raw_domain, str) and raw_domain.strip()
                else ""
            )
            raw_url = offer.get("url")
            product_url = (
                raw_url.strip()
                if isinstance(raw_url, str) and raw_url.strip()
                else None
            )
            raw_avail = offer.get("availability")
            availability = (
                raw_avail.strip()
                if isinstance(raw_avail, str) and raw_avail.strip()
                else None
            )
            raw_cond = offer.get("condition")
            condition = (
                raw_cond.strip()
                if isinstance(raw_cond, str) and raw_cond.strip()
                else None
            )

            price_obj = offer.get("price")
            raw_price_val = None
            raw_currency = None
            if isinstance(price_obj, dict):
                raw_price_val = price_obj.get("price")
                raw_currency = price_obj.get("currency")

            currency = (
                raw_currency.strip().upper()
                if isinstance(raw_currency, str) and raw_currency.strip()
                else None
            )

            ineligible_reason: str | None = None
            price_minor: int | None = None
            reported_price_raw: str | None = (
                str(raw_price_val)
                if raw_price_val is not None and not isinstance(raw_price_val, bool)
                else None
            )

            if not title:
                ineligible_reason = "missing product title"
            elif not domain:
                ineligible_reason = "missing merchant domain"
            elif currency is None:
                ineligible_reason = "missing offer currency"
            elif currency != CHANNEL3_CURRENCY:
                ineligible_reason = (
                    f"unsupported currency {currency!r}; only GBP is accepted"
                )
            else:
                try:
                    price_minor, reported_price_raw = parse_major_to_pence(
                        raw_price_val
                    )
                except ValueError as exc:
                    ineligible_reason = str(exc)

            is_eligible = ineligible_reason is None and price_minor is not None
            if is_eligible:
                eligible += 1
            else:
                rejected += 1

            candidates.append(
                NormalizedOfferCandidate(
                    provider_product_id=product_id,
                    provider_offer_ref=_build_offer_ref(
                        product_id, domain or "unknown", product_url, idx
                    ),
                    product_title=title or "(untitled product)",
                    brand_name=brand_name,
                    merchant_domain=domain or "(unknown merchant)",
                    reported_price_raw=reported_price_raw,
                    price_minor=price_minor if is_eligible else None,
                    currency=currency,
                    product_url=product_url,
                    image_url=image_url,
                    availability=availability,
                    condition=condition,
                    locale_country=CHANNEL3_COUNTRY,
                    locale_language=CHANNEL3_LANGUAGE,
                    locale_currency=CHANNEL3_CURRENCY,
                    retrieved_at=fetched_at,
                    costing_eligible=is_eligible,
                    ineligible_reason=ineligible_reason,
                )
            )

    next_token = payload.get("next_page_token")
    return Channel3SearchResult(
        query=query,
        locale_country=CHANNEL3_COUNTRY,
        locale_language=CHANNEL3_LANGUAGE,
        locale_currency=CHANNEL3_CURRENCY,
        retrieved_at=fetched_at,
        offers=candidates,
        eligible_count=eligible,
        rejected_count=rejected,
        next_page_token=next_token if isinstance(next_token, str) else None,
    )



class Channel3Client:
    """Small, bounded HTTP adapter for Channel3 ``POST /v1/search``."""

    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str = "https://api.trychannel3.com",
        timeout_seconds: float = 10.0,
        transport: httpx.BaseTransport | None = None,
        sleep_fn: Callable[[float], None] | None = None,
    ) -> None:
        self._api_key = api_key.strip() if isinstance(api_key, str) else ""
        try:
            parsed_base = urlsplit(base_url)
            base_port = parsed_base.port
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "Channel3 API base URL must be https://api.trychannel3.com"
            ) from exc
        if (
            parsed_base.scheme != "https"
            or parsed_base.hostname != "api.trychannel3.com"
            or parsed_base.username is not None
            or parsed_base.password is not None
            or base_port not in (None, 443)
            or parsed_base.path
            or parsed_base.query
            or parsed_base.fragment
            or "?" in base_url
            or "#" in base_url
        ):
            raise ValueError("Channel3 API base URL must be https://api.trychannel3.com")
        self._base_url = "https://api.trychannel3.com"
        self._timeout = max(0.5, min(float(timeout_seconds), 30.0))
        self._transport = transport
        self._sleep_fn = sleep_fn

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    def search_offers(
        self,
        query: str,
        *,
        limit: int = CHANNEL3_DEFAULT_LIMIT,
        in_stock_only: bool = True,
        max_attempts: int = 1,
    ) -> Channel3SearchResult:
        """Search Channel3 with explicit GB/en/GBP locale."""
        if not self.is_configured:
            raise Channel3UnconfiguredError(
                "Channel3 material search is not configured (missing server API key)"
            )

        cleaned_query = query.strip() if isinstance(query, str) else ""
        if not cleaned_query:
            raise ValueError("search query must not be empty")
        if len(cleaned_query) > CHANNEL3_MAX_QUERY_LENGTH:
            raise ValueError(
                f"search query exceeds maximum length of {CHANNEL3_MAX_QUERY_LENGTH} characters"
            )
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ValueError("limit must be an integer")
        if limit < 1 or limit > CHANNEL3_MAX_LIMIT:
            raise ValueError(f"limit must be between 1 and {CHANNEL3_MAX_LIMIT}")

        bounded_attempts = max(1, min(int(max_attempts), 2))
        availability = ["InStock"] if in_stock_only else ["InStock", "OutOfStock"]
        body = {
            "query": cleaned_query,
            "limit": limit,
            "filters": {
                "conditions": ["new"],
                "availability": availability,
            },
            "config": {
                "country": CHANNEL3_COUNTRY,
                "language": CHANNEL3_LANGUAGE,
                "currency": CHANNEL3_CURRENCY,
                "mode": "default",
            },
        }
        headers = {
            "x-api-key": self._api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        return self._execute_search(
            url=f"{self._base_url}/v1/search",
            body=body,
            headers=headers,
            cleaned_query=cleaned_query,
            bounded_attempts=bounded_attempts,
        )

    def _execute_search(
        self,
        *,
        url: str,
        body: dict,
        headers: dict[str, str],
        cleaned_query: str,
        bounded_attempts: int,
    ) -> Channel3SearchResult:
        last_error: Channel3Error | None = None
        with httpx.Client(
            timeout=httpx.Timeout(self._timeout),
            transport=self._transport,
        ) as client:
            for attempt in range(1, bounded_attempts + 1):
                try:
                    response = client.post(url, json=body, headers=headers)
                except httpx.TimeoutException as exc:
                    last_error = Channel3TimeoutError(
                        "Channel3 search request timed out"
                    )
                    if attempt < bounded_attempts:
                        continue
                    raise last_error from exc
                except httpx.HTTPError as exc:
                    last_error = Channel3UnavailableError(
                        "Channel3 search service could not be reached"
                    )
                    if attempt < bounded_attempts:
                        continue
                    raise last_error from exc

                status = response.status_code
                if status == 200:
                    try:
                        payload = response.json()
                    except ValueError as exc:
                        raise Channel3ResponseError(
                            "Channel3 returned non-JSON response"
                        ) from exc
                    return normalize_search_payload(
                        payload,
                        query=cleaned_query,
                        retrieved_at=datetime.now(timezone.utc),
                    )

                if status in (401, 403):
                    raise Channel3AuthError(
                        "Channel3 authentication failed; check server configuration"
                    )
                if status == 402:
                    raise Channel3AuthError(
                        "Channel3 search credits are exhausted on the configured account"
                    )
                if status == 429:
                    retry_after = _parse_retry_after(
                        response.headers.get("Retry-After")
                    )
                    last_error = Channel3RateLimitError(
                        "Channel3 rate limit reached; retry later",
                        retry_after_seconds=retry_after,
                    )
                    if (
                        attempt < bounded_attempts
                        and retry_after is not None
                        and retry_after <= CHANNEL3_MAX_RETRY_AFTER_SECONDS
                        and self._sleep_fn is not None
                    ):
                        self._sleep_fn(float(retry_after))
                        continue
                    raise last_error
                if status in (400, 422):
                    raise Channel3ResponseError(
                        "Channel3 rejected the search specification"
                    )
                if status == 504:
                    last_error = Channel3TimeoutError(
                        "Channel3 upstream search timed out"
                    )
                    if attempt < bounded_attempts:
                        continue
                    raise last_error
                if status >= 500:
                    last_error = Channel3UnavailableError(
                        f"Channel3 service error (HTTP {status})"
                    )
                    if attempt < bounded_attempts:
                        continue
                    raise last_error

                raise Channel3UnavailableError(
                    f"Unexpected Channel3 response status (HTTP {status})"
                )

        assert last_error is not None  # pragma: no cover
        raise last_error
