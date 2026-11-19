"""The seed-check command reports dead seeds and new catalogue models with no network."""

from __future__ import annotations

import runpy
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "check_openrouter_seeds.py"


def _load() -> dict[str, Any]:
    return runpy.run_path(str(_SCRIPT))


def _row(
    model_id: object, created: object = None, outputs: Sequence[str] = ("text",)
) -> dict[str, object]:
    row: dict[str, object] = {"id": model_id, "architecture": {"output_modalities": list(outputs)}}
    if created is not None:
        row["created"] = created
    return row


def test_a_seed_missing_from_the_catalogue_is_dead_in_seed_order() -> None:
    seeds = [
        "openrouter/a-lab/one",
        "openrouter/openai/two:free",
        "openrouter/c-lab/three",
        "openrouter/d-lab/four:batch",
    ]
    rows = [_row("openai/two:free", 10)]
    report = _load()["seed_report"](rows, seeds)
    assert report.dead == (
        "openrouter/a-lab/one",
        "openrouter/c-lab/three",
        "openrouter/d-lab/four:batch",
    )


def test_new_rows_of_tracked_authors_are_newest_first() -> None:
    seeds = ["openrouter/anthropic/old"]
    rows = [
        _row("anthropic/old", 100),
        _row("anthropic/a", 200),
        _row("qwen/c", 300),
        _row("google/b", 300),
    ]
    report = _load()["seed_report"](rows, seeds)
    assert report.new == (
        ("openrouter/google/b", 300),
        ("openrouter/qwen/c", 300),
        ("openrouter/anthropic/a", 200),
    )
    assert report.dead == ()


def test_rows_that_are_not_new_are_excluded() -> None:
    seeds = ["openrouter/openai/seed-model"]
    rows: list[Any] = [
        _row("openai/seed-model", 1000),
        _row("openai/good-model", 2000),
        _row("acme/other-author", 2000),
        _row("openai/colon-model:free", 2000),
        _row("~openai/alias-model", 2000),
        _row("openai/video-model", 2000, outputs=("text", "video")),
        _row("openai/old-model", 999),
        _row("openai/same-date", 1000),
        _row("openai/no-date"),
        _row("openai/bool-date", True),
        {"id": "openai/no-architecture", "created": 2000},
        {"id": 42, "created": 2000},
        {"created": 2000},
        "not-a-mapping",
        None,
    ]
    report = _load()["seed_report"](rows, seeds)
    assert report.new == (("openrouter/openai/good-model", 2000),)
    assert report.dead == ()


def test_with_no_seed_in_the_catalogue_every_qualifying_row_is_new() -> None:
    seeds = ["openrouter/openai/gone"]
    rows = [_row("openai/x", 5), _row("acme/y", 9)]
    report = _load()["seed_report"](rows, seeds)
    assert report.dead == ("openrouter/openai/gone",)
    assert report.new == (("openrouter/openai/x", 5),)


def test_a_seed_row_with_a_bad_created_does_not_set_the_threshold() -> None:
    seeds = ["openrouter/openai/s1", "openrouter/openai/s2"]
    rows = [_row("openai/s1", 100), _row("openai/s2", True), _row("openai/n", 150)]
    report = _load()["seed_report"](rows, seeds)
    assert report.new == (("openrouter/openai/n", 150),)


def _serve(monkeypatch: pytest.MonkeyPatch, payload: object) -> list[str]:
    """Answer the one catalogue GET with ``payload``; return the list of dialed urls."""

    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> object:
            return payload

    calls: list[str] = []

    def fake_get(url: str, **kwargs: object) -> _FakeResponse:
        calls.append(url)
        return _FakeResponse()

    monkeypatch.setattr(httpx, "get", fake_get)
    return calls


def test_main_prints_the_dead_seeds_and_the_new_models(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("AIGW_OPENROUTER_DEFAULT_MODELS", raising=False)
    rows = [
        _row("anthropic/claude-fable-5", 1_700_000_000),
        _row("openai/gpt-test-new", 1_800_000_000),
    ]
    calls = _serve(monkeypatch, {"data": rows, "links": {"next": None}, "total_count": 2})
    runpy.run_path(str(_SCRIPT), run_name="__main__")
    lines = capsys.readouterr().out.splitlines()
    assert calls == ["https://openrouter.ai/api/v1/models?output_modalities=text"]
    assert any(line.startswith("Dead seeds") for line in lines)
    assert any(line.startswith("New models") for line in lines)
    assert "  openrouter/z-ai/glm-5.3-flash" in lines
    # WHY: a dead line is the bare id, and a new line is the id, two spaces and a date. A seed
    # that is in the catalogue must be in neither part of the report.
    assert "  openrouter/anthropic/claude-fable-5" not in lines
    assert not any(line.startswith("  openrouter/anthropic/claude-fable-5  ") for line in lines)
    assert "  openrouter/openai/gpt-test-new  2027-01-15" in lines


@pytest.mark.parametrize(
    "paging",
    [
        {"links": {"next": "/api/v1/models?output_modalities=text&offset=250"}, "total_count": 1},
        {"links": {"next": None}, "total_count": 500},
    ],
    ids=["next-link", "total-larger-than-the-rows"],
)
def test_main_stops_on_a_paged_catalogue_answer(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], paging: dict[str, object]
) -> None:
    # INVARIANT: one page of the catalogue must never become a report. It would list live
    # seeds as dead.
    monkeypatch.delenv("AIGW_OPENROUTER_DEFAULT_MODELS", raising=False)
    _serve(monkeypatch, {"data": [_row("anthropic/claude-fable-5", 1_700_000_000)], **paging})
    with pytest.raises(SystemExit, match="paged"):
        runpy.run_path(str(_SCRIPT), run_name="__main__")
    assert "Dead seeds" not in capsys.readouterr().out
