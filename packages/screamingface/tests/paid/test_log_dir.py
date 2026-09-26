"""Free test: CI can pin the stack's log directory so artifacts survive a failure."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import LOG_DIR_ENV, work_dir


def test_log_dir_env_pins_the_work_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """INVARIANT: with LOG_DIR_ENV set, child logs land at that exact path — the
    workflow uploads it with if:always(), so a failed run's gateway/engine logs
    outlive the runner instead of dying in a pytest tmp dir."""
    pinned: Path = tmp_path / "paid-logs"
    monkeypatch.setenv(LOG_DIR_ENV, str(pinned))
    assert work_dir(tmp_path_factory) == pinned
    assert pinned.is_dir()


def test_log_dir_defaults_to_session_tmp(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    monkeypatch.delenv(LOG_DIR_ENV, raising=False)
    chosen: Path = work_dir(tmp_path_factory)
    assert chosen.is_dir()
    assert "paid-stack" in chosen.name
