"""Offline smoke tests for the Tipping Point scaffold."""

from fastapi.testclient import TestClient

from tipping_point import __version__
from tipping_point.app import app


def test_package_version_is_declared():
    assert __version__ == "0.1.0"


def test_health_live_returns_ok():
    client = TestClient(app)
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_live_does_not_require_external_credentials():
    """The liveness endpoint must work without any external service or secrets."""
    client = TestClient(app)
    response = client.get("/health/live")
    assert response.status_code == 200
