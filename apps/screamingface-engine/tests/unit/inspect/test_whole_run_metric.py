# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""A row may score the whole run with the eval's own inspect metric (OME-1527, PR 2 of 20).

FEATURE: whole-run metrics (R1). Think of grading as a marking room: the eval's scorer marks
each Case, then a tally clerk turns the marks into one headline. Until now the clerk could
only add and divide. A row that names ``whole_run_metric`` hands the clerk the eval's own
tally sheet: the scorer adapter keeps each graded Case's inspect Score for the run, and the
tally calls the eval's metric over them.

INVARIANT: the mean stays the default. A row that names no metric pins nothing, so no
published revision moves, and no published row opts in.

The worked example pinned below is contracteval's shape, on a small local stand-in: 7 of 10
Cases have no related clause, and a Candidate that always answers "no related clause" scores
0.7 as a mean but 0.0 as F1 (it never finds a clause that exists).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from inspect_ai.scorer import (  # noqa: E402
    CORRECT,
    INCORRECT,
    Metric,
    SampleScore,
    Score,
    Scorer,
    Target,
    accuracy,
    metric,
    scorer,
)
from inspect_ai.solver import TaskState  # noqa: E402

from screamingface_engine.benchmarks.contract import encode_candidate_invocation  # noqa: E402
from screamingface_engine.benchmarks.graded_answer import graded_answer_payload  # noqa: E402
from screamingface_engine.benchmarks.shared_grading.benchmark_aggregation import (  # noqa: E402
    GradeRequest,
)
from screamingface_engine.benchmarks.shared_grading.payloads import TextPayload  # noqa: E402
from screamingface_engine_inspect import benchmarks, single_shot  # noqa: E402
from screamingface_engine_inspect.benchmarks import BENCHMARKS, BenchmarkSpec  # noqa: E402
from screamingface_engine_inspect.envelopes import CHECK_SCHEMA, build_case_grade  # noqa: E402
from screamingface_engine_inspect.prepare import PreparedCase, _write_cases  # noqa: E402
from screamingface_engine_inspect.scorer_adapter import inspect_grade_case  # noqa: E402
from screamingface_engine_inspect.single_shot import (  # noqa: E402
    AggregateError,
    ImportedBenchmark,
    benchmark_aggregate_async,
    single_shot_benchmark,
)

#: The reply a Candidate gives when it finds nothing; the stand-in's answer key for a Case
#: with no clause.
_NONE: str = "no related clause"


@scorer(metrics=[accuracy()])
def clause_match() -> Scorer:
    """Stand-in for contracteval's scorer: 1 when the reply contains the gold text, else 0.

    It does NOT reproduce contracteval's grading (every gold sentence, case-folded "no
    related clause"); it only gives the tally per-Case marks in the same shape.
    """

    async def score(state: TaskState, target: Target) -> Score:
        reply: str = state.output.completion
        return Score(value=1 if target.text in reply else 0, answer=reply)

    return score


@metric
def clause_f1() -> Metric:
    """F1 over the run's confusion matrix: a true positive is a found clause that exists.

    ``has_clause`` is answer-key material, so it is read from the Sample metadata (the
    private Grading Material), never from the Score the Report publishes.
    """

    def compute(scores: list[SampleScore]) -> float:
        true_pos: int = 0
        false_pos: int = 0
        false_neg: int = 0
        for sample in scores:
            has_clause: bool = bool((sample.sample_metadata or {})["has_clause"])
            said_none: bool = _NONE in str(sample.score.answer)
            if has_clause and not said_none and sample.score.as_float() == 1.0:
                true_pos += 1
            elif has_clause:
                false_neg += 1
            elif not said_none:
                false_pos += 1
        denominator: int = 2 * true_pos + false_pos + false_neg
        return 0.0 if denominator == 0 else 2 * true_pos / denominator

    return compute


@metric
def found_rate() -> Metric:
    """The share of graded Cases whose clause was found: shows how many Cases the tally saw."""

    def compute(scores: list[SampleScore]) -> float:
        return sum(sample.score.as_float() for sample in scores) / len(scores)

    return compute


@metric
def clause_counts() -> Metric:
    """A dict-valued stand-in, as inspect allows: keys that no Case carries."""

    def compute(scores: list[SampleScore]) -> dict[str, float]:
        found: float = sum(sample.score.as_float() for sample in scores)
        return {"found_rate": found / len(scores), "cases": float(len(scores))}

    return compute


def _cases(has_clause: list[bool]) -> list[PreparedCase]:
    """Contracteval-shaped Cases: the gold clause or "no related clause" as the answer key,
    and whether a clause exists in the private Sample metadata."""

    return [
        {
            "case": {
                "id": index,
                "case_id": str(index),
                "input": f"Find the clause in contract {index}.",
            },
            "grading_material": {
                "target": f"clause {index}" if clause else _NONE,
                "metadata": {"has_clause": clause},
            },
        }
        for index, clause in enumerate(has_clause, start=1)
    ]


def _row(case_id: int, answer: str) -> dict[str, object]:
    """One graded-answer row, as the run hands the aggregate route a Candidate's answer."""

    record: dict[str, object] = {
        "schema": CHECK_SCHEMA,
        "case_id": case_id,
        "attempt": 1,
        "answer": answer,
        "status": "completed",
        "refusal": None,
        "finish_reason": "stop",
        "execution": None,
    }
    return graded_answer_payload(
        case_id,
        encode_candidate_invocation(answer, "stop", None),
        [build_case_grade(case_id, [record])],
    )


def _benchmark(
    key: str,
    metric_factory: Callable[[], Any] | None,
    scorer_factory: Callable[[], Any] = clause_match,
) -> ImportedBenchmark:
    """A stand-in Benchmark graded by ``clause_match`` (or another scorer), with or without a
    whole-run metric."""

    return single_shot_benchmark(
        benchmark_key=key,
        title="Clause finding",
        description="A contracteval-shaped stand-in.",
        focus="Contracts",
        dataset_url="https://example.test/contracts",
        case_count=10,
        revision_pins=("stand-in",),
        scorer_factory=scorer_factory,
        prepare=lambda out: {},
        install=lambda node, assets: None,
        with_check_surface=False,
        difficulty="easy",
        whole_run_metric_factory=metric_factory,
    )


async def _aggregate(
    benchmark: ImportedBenchmark, root: Path, has_clause: list[bool], answers: list[str]
) -> dict[str, Any]:
    """Grade one answer per Case through the plugin's own aggregate."""

    _write_cases(_cases(has_clause), root)
    rows: str = json.dumps([_row(index, answer) for index, answer in enumerate(answers, start=1)])
    return await benchmark_aggregate_async(
        benchmark, rows, root, case_ids=tuple(range(1, len(answers) + 1))
    )


#: 7 of 10 Cases have no clause — contracteval's 70% (2,938 of 4,182).
_SEVENTY_PERCENT_NONE: list[bool] = [True, True, True] + [False] * 7


# ── 1. the tally ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_always_answering_no_clause_scores_the_mean_by_default(tmp_path: Path) -> None:
    result: dict[str, Any] = await _aggregate(
        _benchmark("clause-mean", None), tmp_path, _SEVENTY_PERCENT_NONE, [_NONE] * 10
    )

    assert result["score"] == 0.7


@pytest.mark.asyncio
async def test_a_row_naming_f1_scores_the_same_replies_zero(tmp_path: Path) -> None:
    """The worked example: the mean rewards saying "nothing here" on a mostly-empty set; the
    eval's own F1 does not, because it never finds a clause that exists."""

    result: dict[str, Any] = await _aggregate(
        _benchmark("clause-f1", clause_f1), tmp_path, _SEVENTY_PERCENT_NONE, [_NONE] * 10
    )

    assert result["score"] == 0.0
    assert result["coverage"] == 1.0
    # INVARIANT: the private "has a clause" fact reached the metric, never the Report.
    assert "has_clause" not in json.dumps(result)


@pytest.mark.asyncio
async def test_finding_every_clause_scores_one_as_f1(tmp_path: Path) -> None:
    answers: list[str] = ["clause 1", "clause 2", "clause 3"] + [_NONE] * 7

    result: dict[str, Any] = await _aggregate(
        _benchmark("clause-f1-perfect", clause_f1), tmp_path, _SEVENTY_PERCENT_NONE, answers
    )

    assert result["score"] == 1.0


@pytest.mark.asyncio
async def test_a_dict_metric_is_refused_by_name(tmp_path: Path) -> None:
    """WHY: a Named Score is the mean of a column every graded Case carries (the SDK's
    promise); a dict's ``found_rate`` and ``cases`` are columns no Case has, so publishing
    them would show numbers no Case Grade explains."""

    with pytest.raises(
        AggregateError, match=r"clause_counts returned a dict \(found_rate, cases\)"
    ):
        await _aggregate(
            _benchmark("clause-dict", clause_counts), tmp_path, [True] * 2, ["clause 1"] * 2
        )


@pytest.mark.asyncio
async def test_a_metric_reading_metadata_the_cases_lack_is_named(tmp_path: Path) -> None:
    """WHY: the metric is the eval's code and runs after every Candidate call is paid; a bare
    KeyError would name neither the metric nor what it missed."""

    cases: list[PreparedCase] = _cases([True, False])
    for case in cases:
        del case["grading_material"]["metadata"]
    _write_cases(cases, tmp_path)
    rows: str = json.dumps([_row(1, "clause 1"), _row(2, _NONE)])

    with pytest.raises(AggregateError, match="clause_f1 failed: KeyError: 'has_clause'"):
        await benchmark_aggregate_async(
            _benchmark("clause-no-metadata", clause_f1), rows, tmp_path, case_ids=(1, 2)
        )


@scorer(metrics=[accuracy()])
def letter_match() -> Scorer:
    """Marks in inspect's letters, as most of its own scorers do: "C" or "I"."""

    async def score(state: TaskState, target: Target) -> Score:
        return Score(value=CORRECT if target.text in state.output.completion else INCORRECT)

    return score


@pytest.mark.asyncio
async def test_a_letter_mark_reaches_the_metric_as_a_number(tmp_path: Path) -> None:
    """WHY: inspect reduces each Sample's Score before any metric runs, so "C" arrives as 1.0;
    without that step ``as_float()`` on "C" raises, and found_rate could not run."""

    result: dict[str, Any] = await _aggregate(
        _benchmark("clause-letters", found_rate, letter_match),
        tmp_path,
        [True] * 2,
        ["clause 1", "wrong"],
    )

    assert result["score"] == 0.5


@metric(scores="unreduced")
def raw_found_rate() -> Metric:
    """found_rate declared to read each Sample's raw Score, as inspect's ``frequency`` does."""

    def compute(scores: list[SampleScore]) -> float:
        return sum(sample.score.as_float() for sample in scores) / len(scores)

    return compute


@pytest.mark.asyncio
async def test_a_metric_asking_for_unreduced_scores_is_refused_by_name(tmp_path: Path) -> None:
    """WHY: inspect hands such a metric the raw "C"; the store keeps the reduced 1.0, so the
    metric would read numbers inspect never gives it."""

    with pytest.raises(AggregateError, match="raw_found_rate asks for unreduced Scores"):
        await _aggregate(
            _benchmark("clause-unreduced", raw_found_rate), tmp_path, [True] * 2, ["x"] * 2
        )


@pytest.mark.asyncio
async def test_a_failed_case_stays_out_of_the_tally(tmp_path: Path) -> None:
    """A Case with no row never reaches the metric: 3 graded Cases, 1 found → 1/3."""

    benchmark: ImportedBenchmark = _benchmark("clause-missing", found_rate)
    _write_cases(_cases([True] * 4), tmp_path)
    rows: str = json.dumps([_row(1, "clause 1"), _row(2, "x"), _row(3, "y")])

    result: dict[str, Any] = await benchmark_aggregate_async(
        benchmark, rows, tmp_path, case_ids=(1, 2, 3, 4)
    )

    assert result["coverage"] == 0.75
    # 1/3, not 1/4: the metric saw the 3 graded Cases only.
    assert result["score"] == round(1 / 3, 4)


@metric
def percent_rate() -> Metric:
    """xstest's shape: a rate in 0..100, which no Headline Score may be."""

    def compute(scores: list[SampleScore]) -> float:
        return 100.0 * sum(sample.score.as_float() for sample in scores) / len(scores)

    return compute


@metric
def text_metric() -> Metric:
    """A metric that returns no number at all."""

    def compute(scores: list[SampleScore]) -> str:
        return "high"

    return compute


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("key", "factory", "words"),
    [
        ("clause-percent", percent_rate, "percent_rate returned 50.0"),
        ("clause-text", text_metric, "text_metric returned 'high'"),
    ],
)
async def test_a_headline_no_board_can_publish_is_refused_by_the_metrics_name(
    tmp_path: Path, key: str, factory: Callable[[], Any], words: str
) -> None:
    # WHY refuse, never clip: a Headline Score is a number up to 1, higher-is-better; a
    # percent or a word published as one is the wrong number under the eval's name.
    with pytest.raises(AggregateError, match=words):
        await _aggregate(_benchmark(key, factory), tmp_path, [True] * 2, ["clause 1"] * 2)


# ── 2. the scorer adapter's store ────────────────────────────────────────────────────────


def _request(case_id: int, answer: str) -> GradeRequest:
    return GradeRequest(
        case_id=case_id,
        input=TextPayload(text=f"Find the clause in contract {case_id}."),
        answer=TextPayload(text=answer),
        row={},
        material={"target": f"clause {case_id}", "metadata": {"has_clause": True}},
    )


@scorer(metrics=[accuracy()])
def slow_in_reverse() -> Scorer:
    """Marks Case 1 last: proves the store keys each Score by its own Case under overlap."""

    async def score(state: TaskState, target: Target) -> Score:
        await asyncio.sleep(0.01 * (4 - int(state.sample_id)))
        return Score(value=1 if target.text in state.output.completion else 0)

    return score


@pytest.mark.asyncio
async def test_concurrent_cases_each_keep_their_own_score() -> None:
    """Up to four judged Cases grade at once (OME-1527 PR 4); a Score never lands on another
    Case's key."""

    kept: dict[int, SampleScore] = {}
    grade = inspect_grade_case(slow_in_reverse(), kept_scores=kept)

    await asyncio.gather(
        grade(_request(1, "clause 1")), grade(_request(2, "no")), grade(_request(3, "clause 3"))
    )

    assert {case_id: kept[case_id].score.value for case_id in kept} == {1: 1.0, 2: 0.0, 3: 1.0}
    assert kept[2].sample_id == 2
    assert kept[2].sample_metadata == {"has_clause": True}


@scorer(metrics=[accuracy()])
def unmappable() -> Scorer:
    """A scorer whose value the adapter cannot map: the Case fails by name."""

    async def score(state: TaskState, target: Target) -> Score:
        return Score(value=[1, 2])

    return score


@pytest.mark.asyncio
async def test_a_failed_case_keeps_no_score() -> None:
    kept: dict[int, SampleScore] = {}

    outcome = await inspect_grade_case(unmappable(), kept_scores=kept)(_request(1, "x"))

    assert outcome.failure_code == "invalid_score_value"
    assert kept == {}


# ── 3. the row ───────────────────────────────────────────────────────────────────────────


def test_no_published_row_opts_in_so_no_revision_moves() -> None:
    """INVARIANT: honouring the eval's metric is a per-Benchmark owner decision, never a
    default; test_published_revisions pins the revisions this keeps still."""

    assert [spec.key for spec in BENCHMARKS if spec.whole_run_metric is not None] == []
    assert all(benchmarks._whole_run_metric_pins(spec) == () for spec in BENCHMARKS)


def _spec(**overrides: Any) -> BenchmarkSpec:
    """gsm8k's real row with overrides; the benchmark caches are patched per test."""

    gsm8k: BenchmarkSpec = next(spec for spec in BENCHMARKS if spec.key == "gsm8k")
    return replace(gsm8k, **overrides)


def _assembled(spec: BenchmarkSpec, monkeypatch: pytest.MonkeyPatch) -> ImportedBenchmark:
    monkeypatch.setattr(benchmarks, "BENCHMARKS", (spec,))
    monkeypatch.setattr(benchmarks, "_ASSEMBLED", {})
    monkeypatch.setattr(single_shot, "_BENCHMARKS_BY_ID", {})
    return benchmarks.imported_benchmark(spec.key)


def test_naming_a_metric_is_benchmark_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    plain: str = _assembled(_spec(), monkeypatch).benchmark.revision
    honoured: ImportedBenchmark = _assembled(
        _spec(whole_run_metric="inspect_evals.hle.metrics:accuracy"), monkeypatch
    )

    assert honoured.benchmark.revision != plain
    assert benchmarks._whole_run_metric_pins(_spec(whole_run_metric="m:x")) == (
        "whole_run_metric=m:x",
    )
    assert honoured.whole_run_metric_factory is not None
    assert getattr(honoured.whole_run_metric_factory(), "__module__", "") == (
        "inspect_evals.hle.metrics"
    )


@pytest.mark.parametrize(
    ("overrides", "words"),
    [
        ({"inverted_grade": True}, "inverted_grade"),
        ({"verdict_grades": {"YES": 1.0}}, "verdict_grades"),
    ],
)
def test_a_metric_beside_a_grade_rewrite_is_refused_at_assembly(
    monkeypatch: pytest.MonkeyPatch, overrides: Mapping[str, Any], words: str
) -> None:
    """WHY: the eval's metric reads the eval's own grades, so a row that rewrites them (the
    flip, a verdict map standing in for the eval's own reducer) cannot also honour it."""

    spec: BenchmarkSpec = _spec(whole_run_metric="inspect_evals.hle.metrics:accuracy", **overrides)

    with pytest.raises(ValueError, match=f"gsm8k: whole_run_metric .*{words}"):
        _assembled(spec, monkeypatch)


def test_an_unreviewed_metric_never_ships(monkeypatch: pytest.MonkeyPatch) -> None:
    """The importer writes an honoured metric as ``TODO:<reference>``; only a reviewer who has
    confirmed it is higher-is-better up to 1 deletes the prefix."""

    spec: BenchmarkSpec = _spec(whole_run_metric="TODO:inspect_evals.xstest.xstest:refusal_rate")

    with pytest.raises(ValueError, match="gsm8k: whole_run_metric is unreviewed"):
        _assembled(spec, monkeypatch)
