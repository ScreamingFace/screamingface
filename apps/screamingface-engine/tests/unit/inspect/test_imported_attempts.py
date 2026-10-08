# pyright: reportMissingImports=false
# WHY file-level: this suite imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""An imported any-of-N Task becomes a Benchmark that asks each Case N times (OME-1458).

FEATURE: the importer reads a Task's any-match epochs as `attempts=N`; the row it writes
carries the field, and assembly puts it on the Benchmark's cover sheet, into its revision and
into the per-Case expression.

INVARIANT: a row without Attempts writes, assembles and renders exactly as before, so no
published Benchmark's row, revision or URL4 moves (`test_published_revisions` unchanged).

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("inspect_ai")

from test_inverted_grade import _assembled, _string_match_spec  # noqa: E402
from test_task_replay_rows import _benchmark, _facts, _imported  # noqa: E402

from screamingface_engine_inspect.task_replay_rows import (  # noqa: E402
    TaskReplayRows,
    render_task_replay_rows,
)
from url4 import render  # noqa: E402


def _rendered(attempts: int) -> TaskReplayRows:
    """The rows the importer writes for an agieval-shaped Task with these Attempts."""

    return render_task_replay_rows(
        "agieval_lsat_ar", _imported(facts=_facts(attempts=attempts)), "TODO"
    )


def test_an_any_of_two_task_writes_attempts_on_its_row() -> None:
    assert _benchmark(_rendered(2)).attempts == 2


def test_a_one_attempt_row_is_written_exactly_as_before() -> None:
    # INVARIANT: the field is written only above 1, so every existing row's text is unchanged.
    assert "attempts" not in _rendered(1).benchmark
    assert _benchmark(_rendered(1)).attempts == 1


def test_attempts_move_the_revision_only_above_one(monkeypatch: pytest.MonkeyPatch) -> None:
    # WHY: any-of-2 and any-of-1 are different numbers for the same answers, so a change of
    # N must never keep a revision its published scores hang off.
    plain: str = str(_assembled(_string_match_spec(), monkeypatch).benchmark.revision)
    one: str = str(_assembled(_string_match_spec(attempts=1), monkeypatch).benchmark.revision)
    two: str = str(_assembled(_string_match_spec(attempts=2), monkeypatch).benchmark.revision)

    assert one == plain
    assert two != plain


def test_an_attempts_row_declares_and_asks_n_times(monkeypatch: pytest.MonkeyPatch) -> None:
    imported: Any = _assembled(_string_match_spec(attempts=2), monkeypatch)
    url4: str = render(imported.benchmark.build(3))

    assert imported.benchmark.declaration.attempts == 2
    assert imported.benchmark.catalog_entry()["attempts"] == 2
    assert "/benchmarks/case-attempts" in url4
    assert url4.count("attempt=2") == 1


def test_a_one_attempt_row_asks_once(monkeypatch: pytest.MonkeyPatch) -> None:
    imported: Any = _assembled(_string_match_spec(), monkeypatch)

    assert "attempts" not in imported.benchmark.catalog_entry()
    assert "case-attempts" not in render(imported.benchmark.build(3))
