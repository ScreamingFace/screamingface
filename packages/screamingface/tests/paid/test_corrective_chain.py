"""Free tests: the ifeval Corrective Loop entry proves its retry chain ran, or says so.

INVARIANT (OME-1527 row 15b, owner decisions): the loop entry is judged by the same
referee as every Fusion entry (an infrastructure failure code turns the press red), and
on top of that its kept Report must show a Case that got past round 1. When none did, the
press stays green with a loud "chain not exercised" warning: an unlucky model is not a
broken pipe, but nobody may read that press as proof the Draft Feedback chain works.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from _corrective_chain import (
    CHAIN_NOT_EXERCISED,
    ChainEvidence,
    chain_lines,
    chain_warning,
    read_chain_evidence,
)
from _panel import CORRECTIVE_CASE_LIMIT, CORRECTIVE_RUN, FUSION_RUN
from test_imported_board_smoke import _report_problems, _smoke_one_board


def _loop_case(
    case_id: int, rounds: int, stop_reason: str, status: str = "scored"
) -> dict[str, Any]:
    """One exported Corrective Loop Case, with the fields the Report carries for a loop."""
    return {
        "case_id": case_id,
        "status": status,
        "stop_reason": stop_reason,
        "rounds_executed": rounds,
        "failures": [],
    }


def _write_report(path: Path, cases: list[dict[str, Any]]) -> Path:
    """Write a Report export shaped like the SDK's (the fields the chain check reads)."""
    path.write_text(json.dumps({"candidates": [{"cases": cases}]}), encoding="utf-8")
    return path


def test_a_case_that_reached_round_two_proves_the_chain(tmp_path: Path) -> None:
    """Case 6 needed all 3 rounds, as it did in the recorded golden: the coaching call
    ran (round 2 is only reachable through it), so the press proved the chain."""
    report: Path = _write_report(
        tmp_path / "ifeval.corrective-loop.json",
        [_loop_case(1, 1, "passed"), _loop_case(6, 3, "max_rounds")],
    )

    evidence: ChainEvidence | None = read_chain_evidence(report)

    assert evidence is not None and evidence.exercised
    assert chain_warning(evidence) is None
    assert chain_lines(evidence) == [
        "    case 1 · 1 round · check passed · scored",
        "    case 6 · 3 rounds · check never passed · scored",
    ]


def test_every_case_passing_round_one_warns_instead_of_failing(tmp_path: Path) -> None:
    """A green loop whose Cases all stopped in round 1 never ran the chain; it must say so."""
    report: Path = _write_report(
        tmp_path / "loop.json", [_loop_case(case_id, 1, "passed") for case_id in range(1, 9)]
    )

    evidence: ChainEvidence | None = read_chain_evidence(report)

    assert evidence is not None and not evidence.exercised
    assert chain_warning(evidence) == CHAIN_NOT_EXERCISED
    assert "chain not exercised" in CHAIN_NOT_EXERCISED


def test_a_case_that_failed_before_the_loop_reported_is_not_counted(tmp_path: Path) -> None:
    """A Case that died on a member's token cap has no rounds; it cannot prove the chain."""
    failed: dict[str, Any] = {"case_id": 2, "status": "failed", "failures": [{"code": "x"}]}
    report: Path = _write_report(tmp_path / "loop.json", [failed, _loop_case(1, 1, "passed")])

    evidence: ChainEvidence | None = read_chain_evidence(report)

    assert evidence is not None and not evidence.exercised
    assert chain_lines(evidence)[0] == "    case 2 · no loop outcome · failed"


def test_no_kept_report_means_no_warning(tmp_path: Path) -> None:
    """evaluate raised, so the entry is already red; a warning on top would only add noise."""
    evidence: ChainEvidence | None = read_chain_evidence(tmp_path / "missing.json")

    assert evidence is None
    assert chain_warning(evidence) is None
    assert chain_lines(evidence) == []


def test_an_infrastructure_code_on_the_loop_turns_the_press_red() -> None:
    """Same referee as every Fusion entry: a broken check route surfaces as scorer_error,
    which is our pipe, not the model, so it fails the press named by the entry's label."""
    broken = SimpleNamespace(stage="grading", code="scorer_error", message="check route died")
    cases: list[SimpleNamespace] = [
        SimpleNamespace(case_id=case_id, status="scored", failures=())
        for case_id in range(1, CORRECTIVE_CASE_LIMIT)
    ] + [SimpleNamespace(case_id=CORRECTIVE_CASE_LIMIT, status="failed", failures=(broken,))]
    report = SimpleNamespace(candidates=SimpleNamespace(only=SimpleNamespace(cases=cases)))

    problems: list[str] = _report_problems(
        "ifeval · corrective loop", cast(Any, report), CORRECTIVE_CASE_LIMIT
    )

    assert problems == ["ifeval · corrective loop: case 8 grading/scorer_error — check route died"]


class _RecordingClient:
    """A client that records what evaluate was asked and returns a healthy loop Report."""

    def __init__(self) -> None:
        self.calls: list[tuple[object, dict[str, object]]] = []

    def evaluate(self, candidate: object, **kwargs: object) -> Any:
        """Record the request; hand back an all-scored Report that exports to disk."""
        self.calls.append((candidate, kwargs))
        limit: int = cast(int, kwargs["limit"])
        cases = [SimpleNamespace(case_id=i, status="scored", failures=()) for i in range(limit)]
        report = SimpleNamespace(candidates=SimpleNamespace(only=SimpleNamespace(cases=cases)))
        report.export = lambda path: Path(path).write_text("{}", encoding="utf-8")
        return report


def test_the_loop_entry_runs_ifeval_as_a_corrective_loop_and_keeps_its_report(
    tmp_path: Path,
) -> None:
    """The loop entry asks for the loop, on ifeval, for its own Case count, and keeps its
    Report beside the Fusion's instead of overwriting `ifeval.json`."""
    import screamingface as sf

    client = _RecordingClient()

    problems: list[str] = _smoke_one_board(cast(Any, client), "ifeval", tmp_path, CORRECTIVE_RUN)

    assert problems == []
    candidate, kwargs = client.calls[0]
    assert isinstance(candidate, sf.CorrectiveLoop)
    assert kwargs == {"benchmark": "ifeval", "limit": CORRECTIVE_CASE_LIMIT, "progress": False}
    assert (tmp_path / "ifeval.corrective-loop.json").is_file()
    assert not (tmp_path / "ifeval.json").exists()


def test_the_fusion_entry_is_unchanged_by_the_loop() -> None:
    """Every Benchmark still runs as the Fusion under its own name and Report file."""
    assert FUSION_RUN.label("ifeval") == "ifeval"
    assert FUSION_RUN.report_name("ifeval") == "ifeval.json"
    assert CORRECTIVE_RUN.label("ifeval") == "ifeval · corrective loop"
