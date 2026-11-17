# pyright: reportMissingImports=false
# WHY file-level: this suite imports the `inspect` extra's packages, absent in the default
# (extra-less) install the typecheck gate runs against.
"""Whole-run metric tally: a scoring projection tallies the same as the full Case.

FEATURE memory fix 3 (OME-1835), unit 2. The inspect lane's whole-run tally hands the eval's own
inspect metric the graded Cases' Scores. Fed the projections, it must give the same headline,
metrics and Named Scores as fed the full Cases. Whole-run rows are coverage_declare by design
(see the _whole_run_tally docstring), so only that policy is checked here.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai")

# WHY: the inspect lane collects only tests/unit/inspect, so pytest's prepend mode never puts
# tests/unit on sys.path; the shared fixtures (test_result_body, test_candidate_result_contract)
# live there. A full run already has it; the guard keeps the entry single.
_UNIT_TESTS = str(Path(__file__).resolve().parent.parent)
if _UNIT_TESTS not in sys.path:
    sys.path.insert(0, _UNIT_TESTS)

from inspect_ai.scorer import SampleScore, Score, accuracy, mean  # noqa: E402
from test_candidate_result_contract import _grade, _scored_case  # noqa: E402
from test_result_body import _fixtures  # noqa: E402

from screamingface_engine.activity.progress import scoring_projection  # noqa: E402
from screamingface_engine.benchmarks.aggregation import policy_cases  # noqa: E402
from screamingface_engine.benchmarks.contract import CaseResult  # noqa: E402
from screamingface_engine_inspect.single_shot import _whole_run_tally  # noqa: E402


def _cases() -> list[CaseResult]:
    fixtures = _fixtures()
    attempts = fixtures["attempts"].cases[0].model_copy(update={"case_id": 3})
    abstained = fixtures["abstained"].cases[0].model_copy(update={"case_id": 4})
    failed = fixtures["failed_and_missing"].cases[1].model_copy(update={"case_id": 5})
    return [_scored_case(1), _scored_case(2, grade=_grade(score=0.0)), attempts, abstained, failed]


def _kept(cases: list[CaseResult]) -> dict[Any, SampleScore]:
    return {
        case.case_id: SampleScore(score=Score(value=case.grade.score), sample_id=case.case_id)
        for case in cases
        if case.grade is not None and case.grade.score is not None and not case.abstained
    }


@pytest.mark.parametrize("metric", [accuracy, mean], ids=["accuracy", "mean"])
def test_the_whole_run_tally_scores_projections_as_full_cases(metric: Callable[[], Any]) -> None:
    cases = _cases()
    tally = _whole_run_tally(metric(), _kept(cases))
    full = policy_cases(cases, "coverage_declare")
    light = policy_cases([scoring_projection(case) for case in cases], "coverage_declare")
    assert full is not None
    assert light is not None
    assert tally(full) == tally(light)
