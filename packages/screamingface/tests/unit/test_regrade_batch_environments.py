"""A dev batch must never silently use the production Engine or Scoreboard."""

from __future__ import annotations

from typing import Any

import pytest
from test_regrade_batch_script import batch

import screamingface as sf

_ENGINE = "https://fusion.dev.screamingface.ai"
_BOARD = "https://leaderboard.dev.screamingface.ai"


@pytest.mark.parametrize("option,url", [("--engine-url", _ENGINE), ("--scoreboard-url", _BOARD)])
def test_apply_requires_both_endpoint_overrides_before_constructing_a_client(
    option: str, url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []
    monkeypatch.setattr(sf, "Client", lambda **kwargs: calls.append(kwargs))
    with pytest.raises(SystemExit) as exc:
        batch.main(["--apply", option, url])
    assert exc.value.code == 2
    assert calls == []


def test_explicit_dev_endpoints_reach_the_client(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict[str, Any]] = []
    client = object()

    def make_client(**kwargs: Any) -> object:
        captured.append(kwargs)
        return client

    def run(actual: object, args: Any) -> int:
        assert actual is client
        assert args.apply
        return 0

    monkeypatch.setattr(sf, "Client", make_client)
    monkeypatch.setattr(batch, "_run", run)
    assert batch.main(["--apply", "--engine-url", _ENGINE, "--scoreboard-url", _BOARD]) == 0
    assert captured == [{"engine_url": _ENGINE, "scoreboard_url": _BOARD}]


def test_default_production_endpoints_are_still_the_sdk_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = []
    monkeypatch.setattr(sf, "Client", lambda **kwargs: captured.append(kwargs))
    monkeypatch.setattr(batch, "_run", lambda *args: 0)
    assert batch.main(["--apply"]) == 0
    assert captured == [{}]


@pytest.mark.parametrize("mode", [[], ["--resolve", "entry=owner decision"]])
def test_preview_and_local_resolution_need_no_engine_override(mode: list[str]) -> None:
    args = batch._arguments(["--scoreboard-url", _BOARD, *mode])
    assert args.scoreboard_url == _BOARD
    assert args.engine_url is None
