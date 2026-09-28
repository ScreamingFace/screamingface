"""Free tests: the smoke announces each board's verdict the moment it finishes.

INVARIANT: the owner watching a press sees which board broke while the loop is still
running. The smoke is one test looping over the whole shelf, so pytest alone prints
nothing until every board is done — a broken first board stayed invisible for the
whole paid run.
"""

from __future__ import annotations

from test_imported_board_smoke import _progress_line


def test_healthy_board_line_names_position_board_and_duration() -> None:
    """Position/total tells the owner how far the shelf has got; seconds, how slow."""
    line: str = _progress_line(3, 24, "inspect-gpqa_diamond", [], 41.6)

    assert line == "[3/24] inspect-gpqa_diamond … ok (42s)"


def test_failing_board_line_says_failed_with_its_problem_count() -> None:
    """A broken board must read as FAILED on its own line, not only in the final assert."""
    one: str = _progress_line(4, 24, "inspect-frontierscience", ["a"], 7.0)
    two: str = _progress_line(5, 24, "inspect-aime24", ["a", "b"], 7.0)

    assert one == "[4/24] inspect-frontierscience … FAILED: 1 problem (7s)"
    assert two == "[5/24] inspect-aime24 … FAILED: 2 problems (7s)"
