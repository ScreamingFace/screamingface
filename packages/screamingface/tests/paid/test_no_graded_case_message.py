"""Free tests: the "no Case was graded" verdict names the real reason.

INVARIANT: the verdict only says "tolerated model-side code, rerun" when that is true.
The first paid press printed it for Cases that died on `missing_case_row` (not
tolerated), which pointed the owner at a flaky rerun instead of a real failure.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from test_imported_board_smoke import _report_problems


def _report(*cases: SimpleNamespace) -> Any:
    """Wrap Cases in the slice of the SDK Report that the smoke reads."""
    return cast(Any, SimpleNamespace(candidates=SimpleNamespace(only=SimpleNamespace(cases=cases))))


def _failed(code: str) -> SimpleNamespace:
    """One ungraded Case that failed with the given code."""
    failure = SimpleNamespace(stage="candidate", code=code, message="boom")
    return SimpleNamespace(case_id=1, status="failed", failures=(failure,))


def _no_graded_line(problems: list[str]) -> str:
    """Pick out the board-level "no Case was graded" verdict."""
    return next(problem for problem in problems if "no Case was graded" in problem)


def test_only_tolerated_codes_ask_for_a_rerun() -> None:
    """Two 429s: the pipe may be fine, so the honest advice is to rerun."""
    line: str = _no_graded_line(
        _report_problems("inspect-demo", _report(_failed("rate_limited"), _failed("rate_limited")))
    )

    assert "tolerated model-side code" in line
    assert "rerun" in line


def test_non_tolerated_codes_do_not_claim_tolerated() -> None:
    """missing_case_row is not tolerated: the verdict points at the failures, not a rerun."""
    line: str = _no_graded_line(
        _report_problems(
            "inspect-demo", _report(_failed("missing_case_row"), _failed("rate_limited"))
        )
    )

    assert "tolerated" not in line
    assert "rerun" not in line
    assert "case failures" in line


def test_no_failures_at_all_does_not_claim_tolerated() -> None:
    """Ungraded with zero failures: `all()` over nothing is True, so guard the empty case."""
    ungraded = SimpleNamespace(case_id=1, status="failed", failures=())

    line: str = _no_graded_line(_report_problems("inspect-demo", _report(ungraded, ungraded)))

    assert "tolerated" not in line
    assert "no Case reported a failure" in line
