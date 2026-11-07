import runpy
import sys

import pytest
import uvicorn


@pytest.mark.parametrize("arguments,reload", [([], False), (["--reload"], True)])
def test_cli_uses_import_string_and_explicit_reload(monkeypatch, arguments, reload):
    calls = []
    monkeypatch.setattr(sys, "argv", ["tipping_point", *arguments])
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: calls.append((args, kwargs)))
    runpy.run_module("tipping_point", run_name="__main__")
    assert calls == [(("tipping_point.app:app",), {"host": "0.0.0.0", "port": 8000, "reload": reload})]
