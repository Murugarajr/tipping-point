"""One merchant material search sends exactly one Channel3 request, with no automatic retry.

Offline only: an httpx.MockTransport counts every outbound request; no Channel3 call is made.
"""
from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from tipping_point.app import app
from tipping_point.channel3 import Channel3Client
from tests.integration.api_helpers import logged_in_client
from tests.integration.test_material_api import MOCK_CHANNEL3_RESPONSE, _workshop


class CountingTransport(httpx.MockTransport):
    def __init__(self, outcome):
        self.requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return outcome(request)
        super().__init__(handler)


def _timeout(request):
    raise httpx.ReadTimeout("offline timeout", request=request)


def _connection_error(request):
    raise httpx.ConnectError("offline connection error", request=request)


OUTCOMES = {
    "success": (lambda request: httpx.Response(200, json=MOCK_CHANNEL3_RESPONSE), 200),
    "timeout": (_timeout, 504),
    "connection error": (_connection_error, 503),
    # Retry-After of 1 second is within the client's retry window, so a retry would happen if allowed.
    "rate limit": (lambda request: httpx.Response(429, headers={"Retry-After": "1"}, json={"detail": "slow down"}), 429),
}


@pytest.mark.parametrize("name", list(OUTCOMES))
def test_one_search_sends_exactly_one_request_and_never_retries(owned, name):
    outcome, expected_status = OUTCOMES[name]
    transport = CountingTransport(outcome)
    sleeps: list[float] = []
    had_client = hasattr(app.state, "channel3_client")
    previous = getattr(app.state, "channel3_client", None)
    app.state.channel3_client = Channel3Client(
        api_key="fixture-not-a-real-channel3-key", transport=transport, sleep_fn=sleeps.append,
    )
    try:
        client, info = logged_in_client(owned, app=app)
        workshop = _workshop(client, info["csrf"])
        response = client.post(
            f"/api/merchant/workshops/{workshop}/materials/search",
            json={"query": "embroidery needles", "limit": 5, "in_stock_only": True},
            headers={"X-CSRF-Token": info["csrf"]},
        )
    finally:
        if had_client:
            app.state.channel3_client = previous
        else:
            del app.state.channel3_client
    assert response.status_code == expected_status, response.text
    assert len(transport.requests) == 1, f"{name}: {len(transport.requests)} outbound requests"
    assert sleeps == [], "no back-off wait before a retry"
    sent = transport.requests[0]
    assert (sent.method, sent.url.host, sent.url.path) == ("POST", "api.trychannel3.com", "/v1/search")


def test_the_route_requests_a_single_attempt(owned, monkeypatch):
    """The route itself asks for one attempt, independent of the client's own bound."""
    seen = {}

    class Recorder(Channel3Client):
        def search_offers(self, query, **kwargs):  # noqa: D401 - test double
            seen.update(kwargs)
            raise httpx.ReadTimeout("stop before any request")

    had_client = hasattr(app.state, "channel3_client")
    previous = getattr(app.state, "channel3_client", None)
    app.state.channel3_client = Recorder(api_key="fixture-not-a-real-channel3-key",
                                         transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    try:
        client, info = logged_in_client(owned, app=app)
        workshop = _workshop(client, info["csrf"])
        with pytest.raises(httpx.ReadTimeout):
            TestClient(app, raise_server_exceptions=True, cookies=client.cookies).post(
                f"/api/merchant/workshops/{workshop}/materials/search",
                json={"query": "needles"}, headers={"X-CSRF-Token": info["csrf"]})
    finally:
        if had_client:
            app.state.channel3_client = previous
        else:
            del app.state.channel3_client
    assert seen.get("max_attempts") == 1
