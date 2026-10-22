"""The one-command launcher `scripts/workbench-ui` (stdlib only; it runs before any venv)."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import socket
import sys
from pathlib import Path
from types import ModuleType

import pytest

PACKAGE = Path(__file__).resolve().parents[4]
SCRIPT = PACKAGE / "scripts" / "workbench-ui"


def _load() -> ModuleType:
    loader = importlib.machinery.SourceFileLoader("workbench_ui_launcher", str(SCRIPT))
    spec = importlib.util.spec_from_loader("workbench_ui_launcher", loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["workbench_ui_launcher"] = module
    loader.exec_module(module)
    return module


launcher = _load()


def test_the_script_is_executable_with_a_python_shebang() -> None:
    assert SCRIPT.stat().st_mode & 0o111
    assert SCRIPT.read_text().startswith("#!/usr/bin/env python3")


def _assets(tmp_path: Path) -> Path:
    root = tmp_path / "assets"
    (root / "ifeval").mkdir(parents=True)
    (root / "ifeval" / "cases.json").write_text("[]")
    return root


def test_command_runs_the_ui_from_the_package_with_pythonpath_and_assets(tmp_path: Path) -> None:
    assets = _assets(tmp_path)
    argv, env = launcher.build_command(
        ["--port", "9113"], environ={"PATH": "/bin"}, assets=assets, key=None
    )
    assert argv[:6] == ["uv", "run", "--project", str(PACKAGE), "--extra", "runtime"]
    assert argv[6:9] == ["python", "-m", "workbench.ui"]
    assert "--out" in argv and argv[argv.index("--out") + 1] == str(PACKAGE / "workbench-out")
    assert argv[-2:] == ["--port", "9113"]
    assert env["PYTHONPATH"].split(":")[0] == str(PACKAGE / "tests" / "e2e")
    assert env["SCREAMINGFACE_E2E_ASSETS"] == str(assets)
    assert "OPENROUTER_API_KEY" not in env


def test_an_explicit_out_is_not_overridden(tmp_path: Path) -> None:
    argv, _ = launcher.build_command(
        ["--out", "/tmp/x"], environ={}, assets=_assets(tmp_path), key=None
    )
    assert argv.count("--out") == 1 and argv[argv.index("--out") + 1] == "/tmp/x"


def test_paid_key_is_passed_only_as_openrouter_api_key(tmp_path: Path) -> None:
    _, env = launcher.build_command([], environ={}, assets=_assets(tmp_path), key="sk-or-test")
    assert env["OPENROUTER_API_KEY"] == "sk-or-test"


@pytest.mark.parametrize(
    "line",
    [
        "OPENROUTER_KEY=sk-or-abc",
        "OPENROUTER_API_KEY=sk-or-abc",
        'export OPENROUTER_KEY="sk-or-abc"',
        "OPENROUTER_API_KEY='sk-or-abc'   # personal",
    ],
)
def test_key_is_read_from_dotenv_without_loading_anything_else(tmp_path: Path, line: str) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text(f"LINEAR_TOKEN=lin-secret\n# comment\n{line}\nSIGNOZ_TOKEN=s\n")
    assert launcher.resolve_key(environ={}, dotenv=dotenv) == "sk-or-abc"


def test_an_exported_key_wins_over_dotenv(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text("OPENROUTER_KEY=from-file\n")
    assert launcher.resolve_key(environ={"OPENROUTER_API_KEY": "from-env"}, dotenv=dotenv) == (
        "from-env"
    )


def test_no_key_anywhere_is_none(tmp_path: Path) -> None:
    assert launcher.resolve_key(environ={}, dotenv=tmp_path / "missing.env") is None


def test_missing_ifeval_assets_explain_how_to_prepare(tmp_path: Path) -> None:
    problems = launcher.preflight(
        assets=tmp_path / "nothing", port=launcher.free_port_for_tests(), docker_ok=True
    )
    (problem,) = problems
    assert "ifeval" in problem and "screamingface_engine.benchmarks.prepare" in problem


def test_a_busy_port_is_reported(tmp_path: Path) -> None:
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        port = busy.getsockname()[1]
        problems = launcher.preflight(assets=_assets(tmp_path), port=port, docker_ok=True)
    assert any(str(port) in p and "--port" in p for p in problems)


def test_docker_down_is_reported(tmp_path: Path) -> None:
    problems = launcher.preflight(
        assets=_assets(tmp_path), port=launcher.free_port_for_tests(), docker_ok=False
    )
    assert any("Docker" in p for p in problems)


def test_paid_without_a_key_fails_without_echoing_anything_secret(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(launcher, "dotenv_candidates", lambda: [tmp_path / "none.env"])
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(launcher, "docker_running", lambda: True)
    monkeypatch.setenv("SCREAMINGFACE_E2E_ASSETS", str(_assets(tmp_path)))
    code = launcher.main(["--paid", "--check", "--port", str(launcher.free_port_for_tests())])
    assert code == 2
    assert "OPENROUTER" in capsys.readouterr().err


def test_check_mode_reports_ready_and_does_not_launch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(launcher, "docker_running", lambda: True)
    monkeypatch.setenv("SCREAMINGFACE_E2E_ASSETS", str(_assets(tmp_path)))
    monkeypatch.setattr(launcher.os, "execvpe", lambda *a: pytest.fail("must not launch"))
    assert launcher.main(["--check", "--port", str(launcher.free_port_for_tests())]) == 0
    assert "ready" in capsys.readouterr().out


def test_dotenv_falls_back_to_the_main_checkout_from_a_worktree() -> None:
    """In a git worktree `.env` lives in the main checkout, not the worktree."""
    candidates = launcher.dotenv_candidates()
    assert candidates[0] == launcher.REPO / ".env"
    main = launcher.main_checkout()
    if main is not None and main != launcher.REPO:
        assert candidates[-1] == main / ".env"


def test_resolve_key_checks_every_candidate_in_order(tmp_path: Path) -> None:
    first, second = tmp_path / "a.env", tmp_path / "b.env"
    second.write_text("OPENROUTER_KEY=from-second\n")
    assert launcher.resolve_key(environ={}, dotenv=[first, second]) == "from-second"
