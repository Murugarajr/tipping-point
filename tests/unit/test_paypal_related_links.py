"""Related-resource link parsing (offline only).

Fixtures are sanitized copies of the response *shape* PayPal Sandbox returned on
2026-11-07: links on ``api.sandbox.paypal.com``. Synthetic IDs; no payer, token
or credential data.
"""

import asyncio

import httpx
import pytest

from tipping_point.paypal.client import (
    PAYPAL_SANDBOX_BASE_URL, PayPalGateway, PayPalResponseError, parse_capture, parse_refund,
)

REFUND_ID, CAPTURE_ID, AUTH_ID = "0SYNTHREFUND0001A", "0SYNTHCAPTURE001B", "0SYNTHAUTHORIZ01C"
PERMITTED = ("api.sandbox.paypal.com", "api-m.sandbox.paypal.com")


def refund_shape(up_href, *, extra_links=()):
    """Observed Sandbox refund GET/POST shape: no supplementary_data, capture only via the 'up' link."""
    return {
        "id": REFUND_ID, "status": "COMPLETED", "amount": {"currency_code": "GBP", "value": "1.00"},
        "seller_payable_breakdown": {
            "gross_amount": {"currency_code": "GBP", "value": "1.00"},
            "paypal_fee": {"currency_code": "GBP", "value": "0.00"},
            "net_amount": {"currency_code": "GBP", "value": "1.00"},
            "total_refunded_amount": {"currency_code": "GBP", "value": "1.00"},
        },
        "create_time": "2026-11-07T21:34:50Z", "update_time": "2026-11-07T21:34:50Z",
        "links": [
            {"rel": "self", "method": "GET", "href": f"https://api.sandbox.paypal.com/v2/payments/refunds/{REFUND_ID}"},
            {"rel": "up", "method": "GET", "href": up_href},
            *extra_links,
        ],
    }


def capture_shape(up_href):
    """Observed Sandbox capture shape: authorization via the 'up' link; refund link is a POST."""
    return {
        "id": CAPTURE_ID, "status": "REFUNDED", "amount": {"currency_code": "GBP", "value": "1.00"},
        "final_capture": True,
        "seller_receivable_breakdown": {"paypal_fee": {"currency_code": "GBP", "value": "0.23"}},
        "links": [
            {"rel": "self", "method": "GET", "href": f"https://api.sandbox.paypal.com/v2/payments/captures/{CAPTURE_ID}"},
            {"rel": "refund", "method": "POST", "href": f"https://api.sandbox.paypal.com/v2/payments/captures/{CAPTURE_ID}/refund"},
            {"rel": "up", "method": "GET", "href": up_href},
        ],
    }


@pytest.mark.parametrize("host", PERMITTED)
def test_refund_up_link_on_either_sandbox_host_names_the_capture(host):
    parsed = parse_refund(refund_shape(f"https://{host}/v2/payments/captures/{CAPTURE_ID}"))
    assert parsed.capture_id == CAPTURE_ID
    assert (parsed.refund_id, parsed.status, parsed.amount_minor, parsed.currency) == (REFUND_ID, "COMPLETED", 100, "GBP")


@pytest.mark.parametrize("host", PERMITTED)
def test_capture_up_link_on_either_sandbox_host_names_the_authorization(host):
    parsed = parse_capture(capture_shape(f"https://{host}/v2/payments/authorizations/{AUTH_ID}"))
    assert parsed.authorization_id == AUTH_ID and parsed.fee_minor == 23
    # The capture's own POST /refund link is never mistaken for a related authorization.
    assert parse_capture(capture_shape("https://api.sandbox.paypal.com/v2/payments/captures/X")).authorization_id is None


@pytest.mark.parametrize("href", [
    # wrong scheme
    f"http://api.sandbox.paypal.com/v2/payments/captures/{CAPTURE_ID}",
    # live, unrelated and lookalike hosts (exact match only, never substring/suffix)
    f"https://api.paypal.com/v2/payments/captures/{CAPTURE_ID}",
    f"https://api-m.paypal.com/v2/payments/captures/{CAPTURE_ID}",
    f"https://evil.invalid/v2/payments/captures/{CAPTURE_ID}",
    f"https://api.sandbox.paypal.com.evil.invalid/v2/payments/captures/{CAPTURE_ID}",
    f"https://evilapi.sandbox.paypal.com/v2/payments/captures/{CAPTURE_ID}",
    f"https://x.api.sandbox.paypal.com/v2/payments/captures/{CAPTURE_ID}",
    f"https://sandbox.paypal.com/v2/payments/captures/{CAPTURE_ID}",
    f"https://www.sandbox.paypal.com/v2/payments/captures/{CAPTURE_ID}",
    f"https://api.sandbox.paypal.com./v2/payments/captures/{CAPTURE_ID}",
    f"https://API.SANDBOX.PAYPAL.COM/v2/payments/captures/{CAPTURE_ID}",
    # userinfo and ports (including the default port and malformed ones)
    f"https://user@api.sandbox.paypal.com/v2/payments/captures/{CAPTURE_ID}",
    f"https://user:pw@api-m.sandbox.paypal.com/v2/payments/captures/{CAPTURE_ID}",
    f"https://api.sandbox.paypal.com@evil.invalid/v2/payments/captures/{CAPTURE_ID}",
    f"https://api.sandbox.paypal.com:443/v2/payments/captures/{CAPTURE_ID}",
    f"https://api-m.sandbox.paypal.com:8443/v2/payments/captures/{CAPTURE_ID}",
    f"https://api.sandbox.paypal.com:bad/v2/payments/captures/{CAPTURE_ID}",
    # wrong resource kind, version or path shape
    f"https://api.sandbox.paypal.com/v2/payments/authorizations/{CAPTURE_ID}",
    f"https://api.sandbox.paypal.com/v2/payments/refunds/{CAPTURE_ID}",
    f"https://api.sandbox.paypal.com/v1/payments/captures/{CAPTURE_ID}",
    f"https://api.sandbox.paypal.com/v2/checkout/orders/{CAPTURE_ID}",
    f"https://api.sandbox.paypal.com/v2/payments/captures/{CAPTURE_ID}/refund",
    "https://api.sandbox.paypal.com/v2/payments/captures/",
    f"https://api.sandbox.paypal.com/v2/payments/captures/{CAPTURE_ID}%2Fx",
    "https://api.sandbox.paypal.com/v2/payments/captures/A.B",
    "https://api.sandbox.paypal.com/v2/payments/captures/" + "A" * 101,
    f"https://api.sandbox.paypal.com/x/v2/payments/captures/{CAPTURE_ID}",
    # query/fragment
    f"https://api.sandbox.paypal.com/v2/payments/captures/{CAPTURE_ID}?next=https://evil.invalid",
    f"https://api.sandbox.paypal.com/v2/payments/captures/{CAPTURE_ID}#frag",
    f"https://api.sandbox.paypal.com/v2/payments/captures/{CAPTURE_ID}?",
])
def test_untrusted_link_shapes_are_never_relationship_proof(href):
    assert parse_refund(refund_shape(href)).capture_id is None


@pytest.mark.parametrize("rel,method", [("self", "GET"), ("refund", "GET"), ("UP", "GET"), ("up", "POST"), ("up", "PATCH")])
def test_relationship_type_and_method_must_be_exactly_up_get(rel, method):
    payload = refund_shape("https://evil.invalid/ignored")
    payload["links"] = [{"rel": rel, "method": method,
                         "href": f"https://api.sandbox.paypal.com/v2/payments/captures/{CAPTURE_ID}"}]
    assert parse_refund(payload).capture_id is None
    payload["links"][0].pop("method")
    assert parse_refund(payload).capture_id == (CAPTURE_ID if rel == "up" else None)


def test_missing_relationship_is_none_and_contradictions_are_errors():
    payload = refund_shape("https://evil.invalid/ignored")
    payload["links"] = payload["links"][:1]
    assert parse_refund(payload).capture_id is None  # never treated as verified ownership
    # The same capture named on both permitted hosts is consistent ...
    same = refund_shape(f"https://api.sandbox.paypal.com/v2/payments/captures/{CAPTURE_ID}", extra_links=[
        {"rel": "up", "method": "GET", "href": f"https://api-m.sandbox.paypal.com/v2/payments/captures/{CAPTURE_ID}"}])
    assert parse_refund(same).capture_id == CAPTURE_ID
    # ... but two different captures, or a link contradicting related_ids, are rejected.
    with pytest.raises(PayPalResponseError):
        parse_refund(refund_shape(f"https://api.sandbox.paypal.com/v2/payments/captures/{CAPTURE_ID}", extra_links=[
            {"rel": "up", "method": "GET", "href": "https://api-m.sandbox.paypal.com/v2/payments/captures/OTHERCAPTURE"}]))
    with pytest.raises(PayPalResponseError):
        parse_refund({**refund_shape(f"https://api.sandbox.paypal.com/v2/payments/captures/{CAPTURE_ID}"),
                      "supplementary_data": {"related_ids": {"capture_id": "OTHERCAPTURE"}}})


def test_gateway_never_fetches_response_provided_urls():
    """Links naming the legacy Sandbox host, or a hostile host, are parsed but never requested."""
    seen = []

    def transport(request):
        seen.append((request.method, request.url.scheme, request.url.host, request.url.port, request.url.path))
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "offline", "expires_in": 3600})
        if request.url.path == f"/v2/payments/refunds/{REFUND_ID}":
            return httpx.Response(200, json=refund_shape(
                f"https://api.sandbox.paypal.com/v2/payments/captures/{CAPTURE_ID}", extra_links=[
                    {"rel": "next", "method": "GET", "href": "https://evil.invalid/steal"},
                    {"rel": "up", "method": "GET", "href": "https://evil.invalid/v2/payments/captures/EVIL"}]))
        if request.url.path == f"/v2/payments/captures/{CAPTURE_ID}":
            return httpx.Response(200, json=capture_shape(
                f"https://api.sandbox.paypal.com/v2/payments/authorizations/{AUTH_ID}"))
        raise AssertionError(f"unexpected request {request.method} {request.url}")

    async def run():
        async with PayPalGateway(client_id="offline", client_secret="offline",
                                 transport=httpx.MockTransport(transport)) as gateway:
            refund = await gateway.get_refund(REFUND_ID)
            capture = await gateway.get_capture(refund.capture_id)
            assert refund.capture_id == CAPTURE_ID and capture.authorization_id == AUTH_ID
    asyncio.run(run())
    assert PAYPAL_SANDBOX_BASE_URL == "https://api-m.sandbox.paypal.com"
    assert seen == [
        ("POST", "https", "api-m.sandbox.paypal.com", None, "/v1/oauth2/token"),
        ("GET", "https", "api-m.sandbox.paypal.com", None, f"/v2/payments/refunds/{REFUND_ID}"),
        ("GET", "https", "api-m.sandbox.paypal.com", None, f"/v2/payments/captures/{CAPTURE_ID}"),
    ]


def test_outbound_base_url_remains_pinned_to_api_m():
    for base in ("https://api.sandbox.paypal.com", "https://api-m.paypal.com", "http://api-m.sandbox.paypal.com"):
        with pytest.raises(Exception):
            PayPalGateway(client_id="offline", client_secret="offline", base_url=base)
