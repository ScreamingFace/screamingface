"""PORTED to url4.json (OME-1183). See test_serve_config_ported.py for the rules.

The `url4` CLI entry point (url4.cli).

STORY: `url4 --version` and `url4 eval` work on the base install (no serving extra);
`url4 serve` resolves a commands-only config, warns on risky exposure, and hands the
assembled ASGI app to uvicorn — failing fast with clear exit codes (0 ok, 1 runtime,
2 usage/config).

These tests are synchronous: `url4 eval` owns its own event loop via evaluate_sync,
so the tests must not run inside one.
"""

from __future__ import annotations

import io
import json

import pytest

import url4.cli.app as cli
from url4 import __version__


def _commands_file(tmp_path, body: dict | None = None) -> str:
    """Write a minimal valid url4.json and return its path.

    PORTED (OME-1183): the default body's argv is an ARRAY -- the TOML spelling
    "python3 -" went through shlex.split and no longer parses.
    """
    payload = body if body is not None else {"routes": {"commands": {"/py": ["python3", "-"]}}}
    config_file = tmp_path / "url4.json"
    config_file.write_text(json.dumps(payload), encoding="utf-8")
    return str(config_file)


def test_version_prints_and_exits_zero(capsys) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--version"])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"url4 {__version__}"


def test_no_subcommand_is_usage_error() -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main([])
    assert exit_info.value.code == 2


def test_eval_from_argument(capsys) -> None:
    assert cli.main(["eval", "('a', 'b')!'join'"]) == 0
    assert "join" in capsys.readouterr().out


def test_eval_from_stdin(capsys, monkeypatch) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("('x', 'y')!'merge'"))
    assert cli.main(["eval"]) == 0
    assert "merge" in capsys.readouterr().out


def test_eval_empty_is_usage_error(capsys, monkeypatch) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("   "))
    assert cli.main(["eval"]) == 2
    assert "no expression" in capsys.readouterr().err


def test_eval_parse_error_is_runtime_error(capsys) -> None:
    assert cli.main(["eval", "(a::)!'x'"]) == 1
    assert "url4 eval:" in capsys.readouterr().err


def test_serve_wires_app_and_calls_uvicorn(monkeypatch, tmp_path, capsys) -> None:
    captured: dict[str, object] = {}

    def fake_forever(app, host, port) -> int:
        captured["app"] = app
        captured["host"] = host
        captured["port"] = port
        return 0

    monkeypatch.setattr(cli, "_serve_forever", fake_forever)
    config = _commands_file(tmp_path)
    assert cli.main(["serve", "--port", "5001", "--config", config]) == 0
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 5001
    assert callable(captured["app"])
    assert "listening on http://127.0.0.1:5001" in capsys.readouterr().err


def test_serve_without_commands_is_usage_error(tmp_path, monkeypatch, capsys) -> None:
    # The aigateway connector is gone — zero-config serve has no backends and
    # must fail fast with an actionable message, not bind a useless node.
    monkeypatch.chdir(tmp_path)  # isolate from any ambient ./url4.json
    monkeypatch.delenv("URL4_CONFIG", raising=False)
    assert cli.main(["serve"]) == 2
    assert "requires at least one" in capsys.readouterr().err


def test_serve_undeclared_default_route_is_usage_error(tmp_path, capsys) -> None:
    config = _commands_file(tmp_path)
    assert cli.main(["serve", "--default-route", "/absent", "--config", config]) == 2
    assert "not a declared command route" in capsys.readouterr().err


def test_serve_removed_connector_flags_are_rejected(tmp_path) -> None:
    config = _commands_file(tmp_path)
    for flag in (
        ["--route", "/x=m"],
        ["--backend-url", "http://gw"],
        ["--backend-token", "-"],
        ["--processor", "/py"],
    ):
        with pytest.raises(SystemExit) as exit_info:
            cli.main(["serve", "--config", config, *flag])
        assert exit_info.value.code == 2


def test_serve_warns_on_non_loopback_bind_with_commands(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(cli, "_serve_forever", lambda _app, _host, _port: 0)
    config = _commands_file(tmp_path)
    assert cli.main(["serve", "--host", "0.0.0.0", "--config", config]) == 0
    err = capsys.readouterr().err
    assert "WARNING binding non-loopback" in err
    assert "command routes are enabled" in err


def test_serve_forever_without_uvicorn_prints_hint(capsys, hide_uvicorn) -> None:
    # The `hide_uvicorn` fixture makes the extra absent for this test, so the
    # branch runs whether or not the dev venv has uvicorn installed.
    assert cli._serve_forever(object(), "127.0.0.1", 4404) == 2
    assert "url4[server]" in capsys.readouterr().err
