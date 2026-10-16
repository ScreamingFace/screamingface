from __future__ import annotations

from pathlib import Path

import pytest

from workbench.targets import KNOWN_TARGETS, TARGET_ENV, selected_target, start_target


def test_default_target_is_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(TARGET_ENV, raising=False)
    assert selected_target() == "replay"


def test_explicit_target_is_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(TARGET_ENV, "local")
    assert selected_target() == "local"


def test_unknown_target_is_refused_with_the_known_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(TARGET_ENV, "prod")
    with pytest.raises(ValueError) as caught:
        selected_target()
    assert all(name in str(caught.value) for name in KNOWN_TARGETS)


def test_start_target_refuses_an_unknown_name(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="prod"):
        with start_target("prod", tmp_path):
            pass


def test_local_target_skips_without_paid_opt_in(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SCREAMINGFACE_TEST_PAID", raising=False)
    with pytest.raises(pytest.skip.Exception, match="SCREAMINGFACE_TEST_PAID"):
        with start_target("local", tmp_path):
            pass


def test_local_target_skips_without_the_byok_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SCREAMINGFACE_TEST_PAID", "1")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(pytest.skip.Exception, match="OPENROUTER_API_KEY"):
        with start_target("local", tmp_path):
            pass


def test_replay_target_skips_through_the_e2e_gate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SCREAMINGFACE_TEST_E2E", raising=False)
    with pytest.raises(pytest.skip.Exception, match="SCREAMINGFACE_TEST_E2E"):
        with start_target("replay", tmp_path):
            pass
