"""Cron dispatcher entry point (``python -m tipping_point.workflows.dispatcher``), offline.

Disabled mode must be a clean no-op: no Render client (so no RENDER_API_KEY), no database
connection, no PayPal client and no outbound request. Settings are explicit; no .env is read.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

import pytest
from pydantic import ValidationError

import tipping_point
from tipping_point.settings import AppSettings
from tipping_point.workflows import dispatcher

PACKAGES = Path(tipping_point.__file__).resolve().parents[1]

GUARD = '''
import json, os, socket, sys, atexit
attempts = []
def blocked(self, address):
    attempts.append(repr(address))
    raise ConnectionRefusedError("blocked by test harness")
socket.socket.connect = blocked
socket.socket.connect_ex = lambda self, address: (attempts.append(repr(address)) or 111)
def report():
    with open(os.environ["TP_GUARD_REPORT"], "w") as fh:
        json.dump({"connections": attempts, "modules": sorted(m for m in sys.modules if m.split(".")[0] in (
            "render", "tipping_point", "psycopg", "httpx"))}, fh)
atexit.register(report)
'''


def explicit_settings(**overrides):
    return AppSettings(_env_file=None, allow_insecure_dev_cookies=True, **overrides)


def run_entry_point(tmp_path, **env_overrides):
    guard_dir = tmp_path / "guard"
    guard_dir.mkdir(parents=True)
    (guard_dir / "sitecustomize.py").write_text(GUARD)
    workdir = tmp_path / "cwd"  # empty: no .env can be loaded
    workdir.mkdir(parents=True)
    report = tmp_path / "report.json"
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PYTHONPATH": f"{guard_dir}{os.pathsep}{PACKAGES}",
        "TP_GUARD_REPORT": str(report),
        "TIPPING_POINT_ENV": "hosted", "TIPPING_POINT_COOKIE_SECURE": "true",
        "TIPPING_POINT_ALLOW_INSECURE_DEV_COOKIES": "false", "APP_PUBLIC_URL": "https://example.invalid",
        "TIPPING_POINT_DATABASE_URL": "postgresql://noop:noop@127.0.0.1:9/noop",
        "TIPPING_POINT_REMOTE_SETTLEMENT_MODE": "disabled", "TIPPING_POINT_REMOTE_SETTLEMENT_CAMPAIGN_IDS": "",
        **env_overrides,
    }
    assert "RENDER_API_KEY" not in env
    done = subprocess.run([sys.executable, "-m", "tipping_point.workflows.dispatcher"], cwd=workdir, env=env,
                          capture_output=True, text=True, timeout=60)
    return done, json.loads(report.read_text())


def test_entry_point_disabled_without_render_key_is_a_clean_no_op(tmp_path):
    done, guard = run_entry_point(tmp_path)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout.strip().splitlines()[-1]) == {
        "mode": "disabled", "eligible": 0, "submitted": 0, "failed": 0, "runs": []}
    assert "dispatch skipped before client setup" in done.stderr
    assert guard["connections"] == [], "no database or outbound connection"
    loaded = set(guard["modules"])  # under ``python -m`` the dispatcher itself runs as __main__
    assert "tipping_point.settings" in loaded
    assert not any(m == "render" or m.startswith("render.") for m in loaded), "Render SDK never imported"
    assert not {"tipping_point.db.engine", "tipping_point.db.session", "tipping_point.paypal.client",
                "tipping_point.guest.service"} & loaded, "no database layer or PayPal client"
    assert not any(m.startswith(("psycopg", "httpx")) for m in loaded)


def test_entry_point_refuses_unrestricted_and_empty_allowlist_modes_before_any_client(tmp_path):
    enabled, guard = run_entry_point(tmp_path / "a", TIPPING_POINT_REMOTE_SETTLEMENT_MODE="enabled")
    assert enabled.returncode != 0 and "ValidationError" in enabled.stderr
    assert guard["connections"] == [] and not any(m.startswith("render") for m in guard["modules"])
    empty, guard = run_entry_point(tmp_path / "b", TIPPING_POINT_REMOTE_SETTLEMENT_MODE="campaign_allowlist")
    assert empty.returncode != 0 and "at least one campaign UUID" in empty.stderr
    assert guard["connections"] == [] and not any(m.startswith("render") for m in guard["modules"])


def test_main_disabled_never_calls_the_client_factory(capsys):
    def boom():
        raise AssertionError("Render client must not be constructed in disabled mode")
    summary = dispatcher.main(settings=explicit_settings(), client_factory=boom)
    assert summary == {"mode": "disabled", "eligible": 0, "submitted": 0, "failed": 0, "runs": []}
    assert json.loads(capsys.readouterr().out.strip()) == summary


def test_main_active_allowlist_reaches_the_client_and_dispatch_path(monkeypatch, capsys):
    campaign = str(uuid.uuid4())
    settings = explicit_settings(remote_settlement_mode="campaign_allowlist", remote_settlement_campaign_ids=campaign,
                                 render_workflow_slug="tipping-point-workflows")
    client, calls = object(), []
    expected = {"mode": "campaign_allowlist", "eligible": 1, "submitted": 1, "failed": 0, "runs": []}
    monkeypatch.setattr(dispatcher, "dispatch_due", lambda c, s: calls.append((c, s)) or expected)
    factory_calls = []
    summary = dispatcher.main(settings=settings, client_factory=lambda: factory_calls.append(1) or client)
    assert factory_calls == [1] and calls == [(client, settings)] and summary == expected
    assert json.loads(capsys.readouterr().out.strip()) == expected


def test_dispatch_due_guard_still_protects_direct_callers():
    def refusing_session():
        raise AssertionError("the database must not be touched")
    class Client:
        workflows = property(lambda self: (_ for _ in ()).throw(AssertionError("Render API must not be called")))
    disabled = explicit_settings()
    assert dispatcher.dispatch_due(Client(), disabled, session_factory=refusing_session)["submitted"] == 0
    bypassed = disabled.model_copy(update={"remote_settlement_mode": "campaign_allowlist", "remote_settlement_campaign_ids": ""})
    assert dispatcher.remote_dispatch_permitted(bypassed) is False
    assert dispatcher.dispatch_due(Client(), bypassed, session_factory=refusing_session)["eligible"] == 0
    with pytest.raises(ValidationError):
        explicit_settings(remote_settlement_mode="enabled")


def test_tests_import_the_release_worktree_source():
    assert "release-auto-deadline" in str(PACKAGES), PACKAGES
