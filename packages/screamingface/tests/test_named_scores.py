"""Named Scores on the SDK side (OME-1268, PR 2 of 5).

FEATURE: a Benchmark with several scorers sends every score by name in a `scores` field on
each Case Grade and on the Candidate Result; one declared Headline Score stays in `score`.
The SDK must know the key BEFORE any Engine emits it (its decoder refuses unknown keys),
carry it on `sf.CaseGrade` / `sf.CandidateResult`, write it to report.json as a stable key,
and show a `scores` block on the report card.

INVARIANT: a single-scorer Benchmark never sends the key, and its report card renders
byte-identically; report.json always carries the key (`{}` when absent).
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from pathlib import Path
from runpy import run_path
from typing import Any, cast

import pytest
from test_report import candidate, case_results, report
from test_report_panel import body
from test_report_panel import candidate as panel_candidate
from test_report_panel import report as panel_report

import screamingface as sf
from screamingface._evaluation.results import _case_grade
from screamingface._ui.report_view import _scores_html, report_html

# A SQuAD-shaped Case Grade: F1 is the Headline Score, exact match is shown beside it.
_SQUAD_SCORES: dict[str, float | None] = {"f1": 0.667, "exact": 0.0}


def _grade(scores: dict[str, float | None] | None = None, score: float | None = 0.667) -> Any:
    """A Case Grade carrying Named Scores, built the way the decoder would build it."""

    if scores is None:
        return sf.CaseGrade(method="inspect_scorer", score=score, metrics={}, checks=())
    return sf.CaseGrade(method="inspect_scorer", score=score, metrics={}, checks=(), scores=scores)


def _wire_grade(**extra: Any) -> dict[str, Any]:
    """A Case Grade exactly as the Engine's wire sends it, plus any extra keys."""

    return {"method": "inspect_scorer", "score": 0.667, "metrics": {}, "checks": [], **extra}


# --- sf.CaseGrade --------------------------------------------------------------------


def test_case_grade_carries_named_scores_as_a_frozen_mapping() -> None:
    grade = _grade(_SQUAD_SCORES)

    assert dict(grade.scores) == _SQUAD_SCORES
    with pytest.raises(TypeError):
        cast(Any, grade.scores)["f1"] = 1.0


def test_case_grade_named_scores_default_to_empty() -> None:
    # WHY: a single-scorer Benchmark has no Named Scores, and every existing caller
    # constructs a Case Grade without the keyword.
    assert dict(_grade().scores) == {}


def test_case_grade_rejects_a_non_finite_named_score() -> None:
    with pytest.raises(ValueError, match="exact"):
        _grade({"f1": 0.667, "exact": math.nan})


def test_case_grade_allows_none_for_a_scorer_that_could_not_grade() -> None:
    assert dict(_grade({"f1": 0.667, "exact": None}).scores) == {"f1": 0.667, "exact": None}


def test_case_grade_rejects_a_blank_named_score_key() -> None:
    with pytest.raises(ValueError):
        _grade({"": 0.5})


def test_case_grade_to_dict_mirrors_the_wire() -> None:
    # INVARIANT: a Case Grade's dict is the Engine's wire shape one-to-one — the key is
    # absent on a single-scorer Benchmark, exactly as the Engine sends it. The stable
    # `scores` key lives on the Candidate Result (see the test below).
    assert "scores" not in _grade().to_dict()
    assert _grade(_SQUAD_SCORES).to_dict()["scores"] == _SQUAD_SCORES


# --- sf.CandidateResult --------------------------------------------------------------


def _candidate_with_scores(scores: dict[str, float | None], score: float | None = 0.5) -> Any:
    value = candidate("opus", score=score)
    return sf.CandidateResult(
        benchmark=value.benchmark,
        run_id=value.run_id,
        started_at=value.started_at,
        completed_at=value.completed_at,
        name=value.name,
        kind=value.kind,
        url4=value.url4,
        models=value.models,
        operations=value.operations,
        score=score,
        coverage=value.coverage,
        metrics={} if score is None else dict(value.metrics),
        cases=value.cases,
        members=(),
        failures=(),
        usage=sf.Usage(),
        scores=scores,
    )


def test_candidate_result_carries_named_scores() -> None:
    result = _candidate_with_scores({"f1": 0.812, "exact": 0.734})

    assert dict(result.scores) == {"f1": 0.812, "exact": 0.734}
    assert dict(candidate("plain").scores) == {}


def test_an_unscored_candidate_result_cannot_carry_named_scores() -> None:
    # WHY: mirrors the metrics rule — infrastructure failure never becomes a plausible number.
    with pytest.raises(ValueError, match="scores"):
        _candidate_with_scores({"f1": 0.0}, score=None)


def test_candidate_result_to_dict_always_carries_scores() -> None:
    assert candidate("plain").to_dict()["scores"] == {}
    assert _candidate_with_scores({"f1": 0.812}).to_dict()["scores"] == {"f1": 0.812}


# --- the wire decoder ----------------------------------------------------------------


def test_case_grade_decodes_an_optional_scores_key() -> None:
    assert dict(_case_grade(_wire_grade(scores=_SQUAD_SCORES)).scores) == _SQUAD_SCORES


def test_case_grade_without_the_key_decodes_to_no_named_scores() -> None:
    # INVARIANT: every Engine before PR 3 sends no key, and decodes exactly as before.
    assert dict(_case_grade(_wire_grade()).scores) == {}


def test_a_non_mapping_scores_value_is_refused() -> None:
    with pytest.raises(sf.ExecutionError, match="scores"):
        _case_grade(_wire_grade(scores=[0.667, 0.0]))


def test_a_non_finite_wire_named_score_is_refused() -> None:
    with pytest.raises(sf.ExecutionError, match="exact"):
        _case_grade(_wire_grade(scores={"f1": 0.667, "exact": float("inf")}))


# --- report.json round trip ----------------------------------------------------------


def test_scores_round_trip_through_report_json(tmp_path: Path) -> None:
    helper = Path(__file__).parents[1] / "examples" / "helpers.py"
    load_candidate_result = cast(
        Callable[..., sf.CandidateResult], run_path(str(helper))["load_candidate_result"]
    )
    graded = case_results()[0]
    cases = (
        sf.CaseResult(
            case_id=graded.case_id,
            input=graded.input,
            output=graded.output,
            finish_reason=graded.finish_reason,
            grade=_grade(_SQUAD_SCORES),
            failures=(),
            metadata={},
        ),
    ) + case_results()[1:]
    value = candidate("squad-run", cases=cases)
    result = sf.CandidateResult(
        benchmark=value.benchmark,
        run_id=value.run_id,
        started_at=value.started_at,
        completed_at=value.completed_at,
        name=value.name,
        kind=value.kind,
        url4=value.url4,
        models=value.models,
        operations=value.operations,
        score=0.667,
        coverage=value.coverage,
        metrics={},
        cases=cases,
        members=(),
        failures=(),
        usage=sf.Usage(),
        scores={"f1": 0.667, "exact": 0.0},
    )
    artifact = report(result).export(tmp_path / "report.json")
    written = json.loads(artifact.read_text())["candidates"][0]

    assert written["scores"] == {"f1": 0.667, "exact": 0.0}
    assert written["cases"][0]["grade"]["scores"] == _SQUAD_SCORES
    reloaded = load_candidate_result(str(artifact))
    assert dict(reloaded.scores) == {"f1": 0.667, "exact": 0.0}
    reloaded_grade = reloaded.cases[0].grade
    assert reloaded_grade is not None
    assert dict(reloaded_grade.scores) == _SQUAD_SCORES


# --- the report card -----------------------------------------------------------------


def test_scores_block_renders_one_row_per_named_score_with_the_headline_tagged() -> None:
    html = _scores_html({"f1": 0.812, "exact": 0.734})

    assert ">scores<" in html
    assert html.count("sf-axis'") == 2
    assert ">f1<" in html and ">0.812<" in html
    assert ">exact<" in html and ">0.734<" in html
    # INVARIANT: the headline tag sits on the ranked row only (the first, by the Engine's
    # headline-first order); the others are shown, not ranked.
    assert html.index("headline") < html.index(">exact<")
    assert html.count("headline") == 1


def test_scores_block_is_absent_for_a_single_score_candidate() -> None:
    assert _scores_html({}) == ""
    assert _scores_html({"accuracy": 0.9}) == ""


def test_a_single_score_report_card_renders_byte_identically() -> None:
    plain = panel_candidate("a", 0.62)
    html = body(report_html(panel_report(plain)))

    assert "sf-axes" not in html or "by axis" in html  # no scores block smuggled in
    assert ">scores<" not in html
