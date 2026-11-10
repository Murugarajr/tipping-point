"""Offline checks for Render deployment configuration and the workflow adapter (no DB, no network)."""

from datetime import datetime, timezone
from pathlib import Path
import re
import uuid

import pytest
from fastapi.testclient import TestClient

from tipping_point.db.config import DatabaseConfig
from tipping_point.settings import AppSettings
from tipping_point.workflows.dispatcher import BUCKET_SECONDS, DueWork, idempotency_key
from tipping_point.workflows.tasks import EXPECTED_SCHEMA_REVISION, TaskInputError, parse_campaign_reference

ROOT = Path(__file__).resolve().parents[2]
HOSTED = dict(_env_file=None, environment="hosted", cookie_secure=True,
              public_url="https://tipping-point.example.test", allowed_origins="https://tipping-point.example.test")


def test_database_url_is_postgres_only_and_normalized():
    cfg = DatabaseConfig(_env_file=None, url="postgres://user:pw@db.internal:5432/tipping?sslmode=require")
    assert cfg.database_url == "postgresql+psycopg://user:pw@db.internal:5432/tipping?sslmode=require"
    assert "pw" not in repr(cfg)  # the connection string is excluded from repr
    for bad in ("sqlite:///tipping.db", "mysql://u@h/db", "postgresql://user@host"):
        with pytest.raises(ValueError):
            DatabaseConfig(_env_file=None, url=bad)
    parts = DatabaseConfig(_env_file=None, url="")
    assert parts.url is None and parts.database_url.endswith(f"@{parts.host}:{parts.port}/{parts.name}")


def test_remote_financial_execution_defaults_to_disabled():
    settings = AppSettings(_env_file=None, allow_insecure_dev_cookies=True)
    assert settings.remote_settlement_mode == "disabled"
    assert not settings.remote_settlement_permits(str(uuid.uuid4()))
    campaign = str(uuid.uuid4())
    allow = AppSettings(_env_file=None, allow_insecure_dev_cookies=True, remote_settlement_mode="campaign_allowlist",
                        remote_settlement_campaign_ids=f" {campaign} ,")
    assert allow.remote_settlement_permits(campaign) and not allow.remote_settlement_permits(str(uuid.uuid4()))
    with pytest.raises(ValueError):
        AppSettings(_env_file=None, remote_settlement_campaign_ids="not-a-uuid")
    with pytest.raises(RuntimeError):
        AppSettings(_env_file=None, allow_insecure_dev_cookies=True, remote_settlement_mode="campaign_allowlist").validate_startup()


def test_hosted_startup_requires_https_same_origin_and_secure_cookies():
    AppSettings(**HOSTED).validate_startup()
    with pytest.raises(RuntimeError):
        AppSettings(**{**HOSTED, "cookie_secure": False}).validate_startup()
    # The public origin is always allowed for same-origin browser mutations, never a wildcard.
    other = AppSettings(**{**HOSTED, "allowed_origins": "https://other.example.test"})
    assert other.origins == {"https://other.example.test", "https://tipping-point.example.test"}
    with pytest.raises(RuntimeError):
        AppSettings(**{**HOSTED, "allow_insecure_dev_cookies": True}).validate_startup()
    with pytest.raises(ValueError):
        AppSettings(**{**HOSTED, "public_url": "http://tipping-point.example.test"})
    with pytest.raises(ValueError):  # live PayPal mode is not representable
        AppSettings(**{**HOSTED, "paypal_env": "live"})
    hosted = AppSettings(**{**HOSTED, "paypal_expected_payee": "PAYEE", "paypal_client_id": "id", "paypal_client_secret": "s"})
    assert hosted.reservations_configured  # callbacks derive from the HTTPS public origin


def test_idempotency_keys_are_stable_within_a_bucket_and_change_with_version_or_bucket():
    item = DueWork(str(uuid.uuid4()), str(uuid.uuid4()), 3)
    start = datetime.fromtimestamp(BUCKET_SECONDS * 4_000_000, tz=timezone.utc)
    same = datetime.fromtimestamp(BUCKET_SECONDS * 4_000_000 + BUCKET_SECONDS - 1, tz=timezone.utc)
    later = datetime.fromtimestamp(BUCKET_SECONDS * 4_000_001, tz=timezone.utc)
    assert idempotency_key(item, start) == idempotency_key(item, same)
    assert idempotency_key(item, start) != idempotency_key(item, later)
    assert idempotency_key(item, start) != idempotency_key(DueWork(item.work_id, item.campaign_id, 4), start)
    assert re.fullmatch(r"tp-settle:[0-9a-f-]{36}:v3:b\d+", idempotency_key(item, start))
    assert item.campaign_id not in idempotency_key(item, start)


def test_task_input_accepts_only_canonical_campaign_uuid():
    value = str(uuid.uuid4())
    assert parse_campaign_reference(value) == value
    for bad in (value.upper(), value.replace("-", ""), f"urn:uuid:{value}", 42, None, {"campaign_id": value}):
        with pytest.raises(TaskInputError):
            parse_campaign_reference(bad)


def test_expected_schema_revision_is_the_single_migration_head():
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    assert ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini"))).get_heads() == [EXPECTED_SCHEMA_REVISION]


def test_same_origin_frontend_serving_never_swallows_api_or_health(tmp_path):
    from tipping_point.app import create_app
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><title>spa</title>")
    (tmp_path / "assets" / "app.js").write_text("console.log('asset')")
    (tmp_path / "favicon.svg").write_text("<svg/>")
    (tmp_path.parent / "outside.txt").write_text("private")
    app = create_app(AppSettings(_env_file=None, allow_insecure_dev_cookies=True, serve_frontend=True,
                                 frontend_dist=str(tmp_path)))
    client = TestClient(app)
    for route in ("/", "/workshops", "/host/workshops/new", "/bookings/abc/paypal/return"):
        response = client.get(route)
        assert response.status_code == 200 and "<title>spa</title>" in response.text, route
        assert response.headers["cache-control"] == "no-cache"
    assert client.get("/assets/app.js").text == "console.log('asset')"
    assert client.get("/favicon.svg").text == "<svg/>"
    assert client.get("/assets/missing.js").status_code == 404
    for route in ("/api/does-not-exist", "/api", "/health/unknown"):
        response = client.get(route)
        assert response.status_code == 404 and response.headers["content-type"].startswith("application/json"), route
    assert "private" not in client.get("/../outside.txt").text and "private" not in client.get("/%2e%2e/outside.txt").text
    assert client.get("/health/live").json() == {"status": "ok"}
    assert client.post("/host").status_code in (404, 405)  # the SPA fallback is GET/HEAD only
    with pytest.raises(RuntimeError):
        create_app(AppSettings(_env_file=None, allow_insecure_dev_cookies=True, serve_frontend=True,
                               frontend_dist=str(tmp_path / "missing")))


def test_readiness_stays_503_before_migration_while_liveness_gates_deploys(monkeypatch):
    from tipping_point.app import create_app
    import tipping_point.workflows.tasks as tasks
    unmigrated = {"database_reachable": True, "schema_revision_matches": False}
    monkeypatch.setattr(tasks, "readiness_report", lambda **_: unmigrated)
    client = TestClient(create_app(AppSettings(_env_file=None, allow_insecure_dev_cookies=True)))
    ready = client.get("/health/ready")
    assert ready.status_code == 503 and ready.json() == {"status": "not_ready", "database": True, "schema": False}
    assert client.get("/health/live").status_code == 200  # the Render deploy health check


def test_frontend_serving_is_opt_in():
    from tipping_point.app import create_app
    app = create_app(AppSettings(_env_file=None, allow_insecure_dev_cookies=True))
    assert TestClient(app).get("/host").status_code == 404


def test_render_blueprint_is_secret_free_and_matches_the_adapter():
    text = (ROOT / "render.yaml").read_text()
    assert "type: workflow" in text and "type: cron" in text and "type: web" in text and "databases:" in text
    assert "python -m tipping_point.workflows.render_app" in text
    assert "python -m tipping_point.workflows.dispatcher" in text
    assert "healthCheckPath: /health/live" in text and "healthCheckPath: /health/ready" not in text
    assert re.search(r"key: TIPPING_POINT_REMOTE_SETTLEMENT_MODE\s+value: disabled", text)
    assert re.search(r"key: TIPPING_POINT_RENDER_WORKFLOW_SLUG.*\n\s+fromService:\n\s+type: workflow\n\s+name: tipping-point-workflows\n\s+property: slug", text)
    no_live_mode = text.lower().replace("deliver", "").replace("/health/live", "").replace("liveness", "")
    assert "PAYPAL_ENV" in text and "live" not in no_live_mode  # no live PayPal mode anywhere
    for secret in ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "PAYPAL_EXPECTED_PAYEE", "RENDER_API_KEY", "CHANNEL3_API_KEY"):
        block = text[text.index(f"key: {secret}"):][:120]
        assert "sync: false" in block, secret
    assert ".venv" not in text and ".private" not in text and "sqlite" not in text.lower()
    assert (ROOT / ".python-version").read_text().strip() == "3.13"


def test_render_sdk_registration_when_installed():
    render = pytest.importorskip("render", reason="render SDK not installed")
    import inspect
    from render.workflows.runner import _convert_parameter_info_to_api_model
    from tipping_point.workflows import render_app
    assert render.__version__ == "1.8.0" and isinstance(render_app.app, render.Workflows)
    registry = render_app.app._registry  # the SDK registry that register mode sends to Render
    assert registry.get_task_names() == ["readiness_diagnostic", "settle_campaign"]
    diagnostic, settle = registry.get_task("readiness_diagnostic"), registry.get_task("settle_campaign")
    assert not inspect.iscoroutinefunction(diagnostic.func) and inspect.iscoroutinefunction(settle.func)
    assert diagnostic.parameters == [] and diagnostic.options.timeout_seconds == 60
    assert [_convert_parameter_info_to_api_model(p).to_dict() for p in settle.parameters] == [
        {"name": "campaign_id", "has_default": False, "type": "str"}]  # the only task input
    assert settle.options.retry == render.Retry(max_retries=0, wait_duration_ms=1000)  # no Render-level replay
    assert settle.options.timeout_seconds == 300 and settle.options.plan is None and not settle.workflow
