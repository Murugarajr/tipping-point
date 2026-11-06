"""Channel3 adapter tests with labeled fixtures; no live provider calls."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import httpx
import pytest

from tipping_point.channel3 import (
    Channel3AuthError,
    Channel3Client,
    Channel3RateLimitError,
    Channel3TimeoutError,
    Channel3UnconfiguredError,
    normalize_search_payload,
    parse_major_to_pence,
)


MOCK_CHANNEL3_RESPONSE = {
    "products": [
        {
            "id": "fixture-product-001",
            "title": "Fixture embroidery thread pack",
            "brands": [{"id": "fixture-brand", "name": "Fixture Brand"}],
            "images": [{"url": "https://fixture.invalid/thread.jpg", "cleaned_url": "https://fixture.invalid/thread-square.jpg", "is_main_image": True}],
            "offers": [
                {
                    "url": "https://fixture.invalid/thread-pack",
                    "domain": "fixture.invalid",
                    "price": {"price": 5.99, "currency": "GBP"},
                    "availability": "InStock",
                    "condition": "new",
                }
            ],
        }
    ],
    "next_page_token": None,
}


def test_provider_request_auth_and_explicit_locale():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = request.headers
        seen["body"] = request.read()
        return httpx.Response(200, json=MOCK_CHANNEL3_RESPONSE)

    result = Channel3Client(
        api_key="fixture-only-not-a-real-key",
        transport=httpx.MockTransport(handler),
    ).search_offers("embroidery floss", limit=4)

    import json

    request_body = json.loads(seen["body"])
    assert seen["url"] == "https://api.trychannel3.com/v1/search"
    assert seen["headers"]["x-api-key"] == "fixture-only-not-a-real-key"
    assert request_body["config"] == {
        "country": "GB", "language": "en", "currency": "GBP", "mode": "default"
    }
    assert request_body["limit"] == 4
    assert result.eligible_count == 1
    assert result.offers[0].price_minor == 599


def test_response_normalization_retains_provider_facts_and_timestamp():
    timestamp = datetime(2026, 11, 6, 12, tzinfo=timezone.utc)
    offer = normalize_search_payload(
        MOCK_CHANNEL3_RESPONSE, query="thread", retrieved_at=timestamp
    ).offers[0]
    assert offer.provider_product_id == "fixture-product-001"
    assert offer.product_title == "Fixture embroidery thread pack"
    assert offer.brand_name == "Fixture Brand"
    assert offer.merchant_domain == "fixture.invalid"
    assert offer.product_url == "https://fixture.invalid/thread-pack"
    assert offer.image_url == "https://fixture.invalid/thread-square.jpg"
    assert offer.availability == "InStock"
    assert offer.price_minor == 599 and offer.currency == "GBP"
    assert offer.retrieved_at == timestamp and offer.costing_eligible


@pytest.mark.parametrize(
    ("value", "expected"),
    [("1", 100), ("1.20", 120), (Decimal("9.99"), 999), (10, 1000)],
)
def test_decimal_safe_price_conversion(value, expected):
    assert parse_major_to_pence(value)[0] == expected


@pytest.mark.parametrize(
    "value", [None, True, "", "many", "NaN", "Infinity", 0, -1, "0.001"]
)
def test_missing_invalid_or_ambiguous_price_rejected(value):
    with pytest.raises(ValueError):
        parse_major_to_pence(value)


def test_missing_price_and_unsupported_currency_block_costing():
    payload = {
        "products": [{
            "id": "fixture-invalid",
            "title": "Fixture invalid offers",
            "offers": [
                {"url": "https://fixture.invalid/a", "domain": "fixture.invalid", "price": {"currency": "GBP"}, "availability": "InStock"},
                {"url": "https://fixture.invalid/b", "domain": "fixture.invalid", "price": {"price": 3, "currency": "USD"}, "availability": "InStock"},
            ],
        }]
    }
    result = normalize_search_payload(payload, query="fixture")
    assert result.eligible_count == 0 and result.rejected_count == 2
    assert "price" in result.offers[0].ineligible_reason
    assert "unsupported currency" in result.offers[1].ineligible_reason


def test_unconfigured_provider_fails_explicitly():
    client = Channel3Client(api_key=None)
    assert not client.is_configured
    with pytest.raises(Channel3UnconfiguredError):
        client.search_offers("wool")





def test_reject_provider_offer_result_over_bound():
    products = []
    for index in range(30):
        products.append({
            "id": f"fixture-{index}",
            "title": f"Fixture product {index}",
            "offers": [
                {
                    "url": f"https://fixture.invalid/{index}-{offer_index}",
                    "domain": "fixture.invalid",
                    "price": {"price": "1.00", "currency": "GBP"},
                    "availability": "InStock",
                }
                for offer_index in range(3)
            ],
        })
    result = normalize_search_payload({"products": products}, query="fixture")
    assert len(result.offers) == 40




def test_rate_limit_honors_retry_after_and_retry_is_bounded():
    calls = 0
    sleeps = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "3"})
        return httpx.Response(200, json=MOCK_CHANNEL3_RESPONSE)

    result = Channel3Client(
        api_key="fixture-key",
        transport=httpx.MockTransport(handler),
        sleep_fn=sleeps.append,
    ).search_offers("wool", max_attempts=9)
    assert calls == 2 and sleeps == [3.0]
    assert result.eligible_count == 1


def test_rate_limit_without_retry_after_is_not_retried():
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429)

    with pytest.raises(Channel3RateLimitError):
        Channel3Client(
            api_key="fixture-key", transport=httpx.MockTransport(handler)
        ).search_offers("wool", max_attempts=2)
    assert calls == 1


def test_provider_auth_error_is_sanitized():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "secret echo"})

    with pytest.raises(Channel3AuthError) as exc:
        Channel3Client(
            api_key="fixture-key", transport=httpx.MockTransport(handler)
        ).search_offers("wool")
    assert "secret echo" not in str(exc.value)
    assert "fixture-key" not in str(exc.value)


def test_transient_upstream_error_is_sanitized_and_bounded():
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, text="secret upstream details")

    from tipping_point.channel3 import Channel3UnavailableError

    with pytest.raises(Channel3UnavailableError) as exc:
        Channel3Client(
            api_key="fixture-key", transport=httpx.MockTransport(handler)
        ).search_offers("wool", max_attempts=2)
    assert calls == 2
    assert "secret upstream details" not in str(exc.value)

def test_timeout_is_sanitized():
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("secret upstream detail")

    with pytest.raises(Channel3TimeoutError) as exc:
        Channel3Client(api_key="fixture-key", transport=httpx.MockTransport(handler)).search_offers("wool")
    assert "secret upstream detail" not in str(exc.value)



@pytest.mark.parametrize(
    "url",
    [
        "http://api.trychannel3.com",
        "https://attacker.invalid",
        "https://api.trychannel3.com.example.invalid",
        "https://api.trychannel3.com/",
        "https://api.trychannel3.com/path",
        "https://user:password@api.trychannel3.com",
        "https://api.trychannel3.com?key=value",
        "https://api.trychannel3.com?",
        "https://api.trychannel3.com#fragment",
        "https://api.trychannel3.com#",
        "https://api.trychannel3.com:444",
        "https://api.trychannel3.com:not-a-port",
    ],
)
def test_arbitrary_or_insecure_base_url_is_rejected(url):
    with pytest.raises(ValueError, match="base URL"):
        Channel3Client(api_key="fixture-key", base_url=url)
