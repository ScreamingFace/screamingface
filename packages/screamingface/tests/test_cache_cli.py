"""`screamingface cache pull` (epic OME-1311, spec decision 14).

FEATURE: community cache, available to a local engine (epic OME-1311).
STORY: as a user of a local engine, one shell command copies the community cache into it.

Pinned here: the command parses a repeatable `--model`, `--url` and `--data-dir`; it runs the same
pull as `sf.cache.pull_from_remote` with progress always on, into the chosen data dir; and it exits
0 when the pull finished, 1 with the reason and hint on stderr when it stopped or was refused, and
130 when interrupted.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from screamingface._cache import pull as pull_module
from screamingface._runtime import cli
from screamingface.cache import CachePullError, PullResult


def _pull(monkeypatch: pytest.MonkeyPatch, outcome: object = None) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def pull_into(models: tuple[str, ...], **kwargs: Any) -> PullResult:
        calls.append({"models": models, **kwargs})
        if isinstance(outcome, BaseException):
            raise outcome
        return PullResult(2, 2, 1, False, True)

    monkeypatch.setattr(pull_module, "pull_into", pull_into)
    return calls


def test_the_parser_reads_models_url_and_data_dir(tmp_path: Path) -> None:
    args = cli._parser().parse_args(
        [
            "cache",
            "pull",
            "--model",
            "m2",
            "--model",
            "m1",
            "--url",
            "https://dev.test",
            "--data-dir",
            str(tmp_path),
        ]
    )

    assert (args.command, args.cache_command) == ("cache", "pull")
    assert args.models == ["m2", "m1"]
    assert args.url == "https://dev.test"
    assert args.data_dir == tmp_path


def test_cache_needs_a_subcommand() -> None:
    with pytest.raises(SystemExit):
        cli._parser().parse_args(["cache"])


def test_a_finished_pull_exits_0_with_progress_on(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = _pull(monkeypatch)

    with pytest.raises(SystemExit) as exited:
        cli.main(["cache", "pull", "--model", "m2", "--model", "m1", "--data-dir", str(tmp_path)])

    assert exited.value.code == 0
    assert calls == [{"models": ("m1", "m2"), "url": None, "data_dir": tmp_path, "progress": True}]


def test_a_stopped_pull_exits_1_with_its_reason_and_hint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _pull(
        monkeypatch,
        CachePullError(
            "The local gateway database has no cache table yet",
            code="local_gateway_missing",
            hint='Run "screamingface up" once to create it, then pull again.',
            result=PullResult(0, 0, 0, False, False),
        ),
    )

    with pytest.raises(SystemExit) as exited:
        cli.main(["cache", "pull", "--data-dir", str(tmp_path)])

    assert exited.value.code == 1
    err = capsys.readouterr().err
    assert "screamingface: The local gateway database has no cache table yet" in err
    assert 'Run "screamingface up"' in err


def test_an_interrupted_pull_exits_130(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _pull(monkeypatch, KeyboardInterrupt())

    with pytest.raises(SystemExit) as exited:
        cli.main(["cache", "pull", "--data-dir", str(tmp_path)])

    assert exited.value.code == 130
    assert "starts over" in capsys.readouterr().err
