"""Free tests: a parallel board worker always hands back a verdict, never an exception.

INVARIANT: one broken board never hides the rest. Boards now run several at a time,
each on its own client; an exception escaping one worker would surface from its future
and abort the collection loop, discarding every other board's verdict.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from test_imported_board_smoke import _smoke_board_timed


class _HealthyClient:
    """A client whose evaluate returns a Report with two graded Cases."""

    def evaluate(self, *_args: object, **_kwargs: object) -> Any:
        """Hand back a two-Case, all-scored Report that exports to disk."""
        case = SimpleNamespace(case_id=1, status="scored", failures=())
        report = SimpleNamespace(
            candidates=SimpleNamespace(only=SimpleNamespace(cases=[case, case]))
        )
        report.export = lambda path: path
        return report


@contextmanager
def _open_healthy() -> Iterator[_HealthyClient]:
    """Open a healthy fake client, like `sf.Client(...)` used as a context manager."""
    yield _HealthyClient()


@contextmanager
def _open_broken() -> Iterator[_HealthyClient]:
    """Fail at open time, the way an unreachable engine would."""
    raise ConnectionError("engine refused the connection")
    yield _HealthyClient()  # pragma: no cover - unreachable, keeps this a generator


def test_healthy_board_returns_no_problems_and_its_duration(tmp_path: Path) -> None:
    """A healthy board's worker returns an empty verdict plus a non-negative duration."""
    problems, seconds = _smoke_board_timed(cast(Any, _open_healthy), "inspect-demo", tmp_path)

    assert problems == []
    assert seconds >= 0


def test_client_that_cannot_open_becomes_that_boards_verdict(tmp_path: Path) -> None:
    """The failure is recorded against the board by name instead of escaping the worker."""
    problems, _seconds = _smoke_board_timed(cast(Any, _open_broken), "inspect-demo", tmp_path)

    assert len(problems) == 1
    assert problems[0].startswith("inspect-demo:")
    assert "engine refused the connection" in problems[0]
