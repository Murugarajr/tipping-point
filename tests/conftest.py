"""Pytest configuration for Tipping Point.

Applies the isolated test-database environment before collection and
restores the original environment afterwards. Unrelated environment
configuration is never modified.
"""

from tests.harness import (
    apply_test_database_env,
    restore_database_env,
    restore_settings_env_file,
    use_local_test_settings_file,
)
import pytest


def pytest_configure(config):
    """Inject the isolated test database and the committed local-test settings file."""
    apply_test_database_env()
    use_local_test_settings_file()


def pytest_unconfigure(config):
    """Restore the original environment and settings configuration exactly as found."""
    restore_settings_env_file()
    restore_database_env()


@pytest.fixture(autouse=True)
def deny_real_provider_network(monkeypatch):
    """MockTransport/ASGI and loopback tests are allowed; external HTTP is not."""
    import httpx
    original_sync = httpx.HTTPTransport.handle_request
    original_async = httpx.AsyncHTTPTransport.handle_async_request

    def sync(transport, request):
        if request.url.host not in ("localhost", "127.0.0.1", "::1"):
            raise AssertionError("Real external HTTP is prohibited in automated tests")
        return original_sync(transport, request)

    async def async_(transport, request):
        if request.url.host not in ("localhost", "127.0.0.1", "::1"):
            raise AssertionError("Real external HTTP is prohibited in automated tests")
        return await original_async(transport, request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", sync)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", async_)
