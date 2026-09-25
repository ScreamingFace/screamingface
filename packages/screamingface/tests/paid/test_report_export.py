"""Free tests: every board that produced a Report leaves it on disk for debugging.

INVARIANT: a failing board's Report is exactly the evidence needed to debug it
(member + synthesizer answers, grade, judge reasoning, run/trace ids). The smoke
used to read it for failure strings and throw the rest away, so debugging a
failed case meant paying for the run again.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from test_imported_board_smoke import _smoke_one_board


class _FakeReport:
    """The slice of the SDK Report the smoke reads, plus a real-shaped export."""

    def __init__(self, cases: list[Any]) -> None:
        self.candidates = SimpleNamespace(only=SimpleNamespace(cases=cases))

    def export(self, path: Path) -> Path:
        """Write a marker document where the smoke asked, like Report.export does."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"schema": "fake-report"}), encoding="utf-8")
        return path


class _FakeClient:
    """A client whose evaluate returns a canned Report, or raises a canned error."""

    def __init__(self, outcome: _FakeReport | Exception) -> None:
        self._outcome = outcome

    def evaluate(self, *_args: object, **_kwargs: object) -> _FakeReport:
        """Hand back the canned outcome — no stack, no spend."""
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


def _failed_case() -> SimpleNamespace:
    """One Case the smoke must flag: ungraded, with a non-tolerated failure code."""
    failure = SimpleNamespace(stage="grading", code="scorer_error", message="judge exploded")
    return SimpleNamespace(case_id=1, status="failed", failures=(failure,))


def test_failing_board_still_leaves_its_report_on_disk(tmp_path: Path) -> None:
    """The board fails the smoke AND its full Report is kept — the failure is the
    moment the evidence matters most."""
    reports_dir: Path = tmp_path / "reports"
    client = _FakeClient(_FakeReport([_failed_case(), _failed_case()]))

    problems: list[str] = _smoke_one_board(cast(Any, client), "inspect-demo", reports_dir)

    assert any("scorer_error" in problem for problem in problems)
    saved: Path = reports_dir / "inspect-demo.json"
    assert json.loads(saved.read_text(encoding="utf-8")) == {"schema": "fake-report"}


def test_board_without_a_report_writes_nothing_and_still_reports(tmp_path: Path) -> None:
    """evaluate raised → there is no Report to keep; the verdict names the cause."""
    reports_dir: Path = tmp_path / "reports"
    client = _FakeClient(RuntimeError("transport died"))

    problems: list[str] = _smoke_one_board(cast(Any, client), "inspect-demo", reports_dir)

    assert problems and "transport died" in problems[0]
    assert not (reports_dir / "inspect-demo.json").exists()
