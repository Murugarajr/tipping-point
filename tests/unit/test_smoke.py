"""Settings and database-independent application smoke regression."""

from fastapi.testclient import TestClient

from tipping_point.app import app


def test_health_live_does_not_require_external_credentials():
    client = TestClient(app)
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}