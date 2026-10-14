# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""A row may score the whole run with the eval's own inspect metric (OME-1527, PR 2 of 20).

FEATURE: whole-run metrics (R1). Think of grading as a marking room: the eval's scorer marks
each Case, then a tally clerk turns the marks into one headline. Until now the clerk could
only add and divide. A row that names ``whole_run_metric`` hands the clerk the eval's own
tally sheet: the scorer adapter keeps each graded Case's inspect Score for the run, and the
tally calls the eval's metric over them. A Case asked several times (Attempts, OME-1458)
hands the metric its Attempt Scores reduced by the Task's own any-of-N reducer, as inspect
does before any metric runs.

INVARIANT: the mean stays the default. A row that names no metric pins nothing, so no
published revision moves, and no published row opts in.

The worked example pinned below is contracteval's shape, on a small local stand-in: 7 of 10
Cases have no related clause, and a Candidate that always answers "no related clause" scores
0.7 as a mean but 0.0 as F1 (it never finds a clause that exists).
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from inspect_ai import Epochs, Task  # noqa: E402
from inspect_ai.dataset import MemoryDataset, Sample  # noqa: E402
from inspect_ai.scorer import (  # noqa: E402
    CORRECT,
    INCORRECT,
    Metric,
    SampleScore,
    Score,
    Scorer,
    ScoreReducer,
    Target,
    accuracy,
    at_least,
    max_score,
    metric,
    pass_at,
    scorer,
)
from inspect_ai.scorer._reducer.registry import reducer_log_names  # noqa: E402
from inspect_ai.solver import TaskState  # noqa: E402
from test_importer_whole_run_choice import _row as _rendered_row  # noqa: E402

from screamingface_engine.benchmarks.contract import encode_candidate_invocation  # noqa: E402
from screamingface_engine.benchmarks.graded_answer import (  # noqa: E402
    CASE_ATTEMPTS_SCHEMA,
    graded_answer_payload,
)
from screamingface_engine.benchmarks.shared_grading.benchmark_aggregation import (  # noqa: E402
    GradeRequest,
)
from screamingface_engine.benchmarks.shared_grading.payloads import TextPayload  # noqa: E402
from screamingface_engine_inspect import benchmarks, single_shot  # noqa: E402
from screamingface_engine_inspect.benchmarks import BENCHMARKS, BenchmarkSpec  # noqa: E402
from screamingface_engine_inspect.envelopes import CHECK_SCHEMA, build_case_grade  # noqa: E402
from screamingface_engine_inspect.import_replay import TaskReplayFacts, _facts_of  # noqa: E402
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
    """WHY: a dict has no single headline until the row names one (``whole_run_headline``);
    guessing a key would publish the wrong number under the eval's name. The dict's keys are
    never Named Scores either: a Named Score is the mean of a column every graded Case carries,
    and ``found_rate`` and ``cases`` are columns no Case has."""

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


# ── 3. Attempts: the metric reads each Case's Attempt Scores reduced by the Task's reducer ─


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reducer", [max_score(), at_least(1), pass_at(2)], ids=["max", "at_least_1", "pass_at_2"]
)
async def test_a_case_keeps_its_attempts_reduced_whatever_order_they_finish(
    reducer: ScoreReducer,
) -> None:
    """Attempt Scores [0, 1] and [1, 0] both reach the metric as 1.0 under every any-of-2
    reducer, as inspect reduces a Sample's epochs before any metric runs.

    WHY both orders: the store used to keep whichever Attempt was graded last, so Case 2
    ([1, 0]) read 0.0 while its Case Result showed it solved. ``slow_in_reverse`` grades
    Case 1 slower than Case 2, so the two Cases' Attempts finish interleaved (2, 1, 2, 1),
    as when the aggregate grades Cases side by side (OME-1527 PR 4).
    """

    kept: dict[int, SampleScore] = {}
    grade = inspect_grade_case(slow_in_reverse(), kept_scores=kept, epoch_reducer=reducer)

    async def ask(case_id: int, answers: list[str]) -> None:
        """Grade one Case's Attempts one after another, as the aggregate's Attempts step does."""

        for answer in answers:
            await grade(_request(case_id, answer))

    await asyncio.gather(ask(1, ["no", "clause 1"]), ask(2, ["clause 2", "no"]))

    assert {case_id: kept[case_id].score.as_float() for case_id in kept} == {1: 1.0, 2: 1.0}


@metric
def per_task_accuracy() -> Metric:
    """ARC-AGI-2's shape: a task is one or more test grids, and the headline averages TASKS,
    each scoring the share of its grids solved, so a task with many grids weighs no more
    than a task with one. The task id is read from the Sample metadata."""

    def compute(scores: list[SampleScore]) -> float:
        by_task: dict[str, list[float]] = {}
        for sample in scores:
            task_id: str = str((sample.sample_metadata or {})["task_id"])
            by_task.setdefault(task_id, []).append(sample.score.as_float())
        return sum(sum(grids) / len(grids) for grids in by_task.values()) / len(by_task)

    return compute


@scorer(metrics=[accuracy()])
def grid_match() -> Scorer:
    """Stand-in for an ARC scorer: 1 when the reply holds the target grid, else 0; a reply of
    "crash" raises, so that Attempt fails by name (``scorer_error``) as a scorer bug would.

    It does NOT compare grids cell by cell; it only gives each Attempt a 0/1 mark.
    """

    async def score(state: TaskState, target: Target) -> Score:
        if state.output.completion == "crash":
            raise RuntimeError("scorer bug")
        return Score(value=1 if target.text in state.output.completion else 0)

    return score


#: ARC-shaped test grids: (task id, Attempt 1's reply, Attempt 2's reply), grid N's target
#: being "grid N". Task A has grids 1 and 2; task B has grid 3.
_ARC_GRIDS: list[tuple[str, str, str]] = [
    ("A", "wrong", "grid 1"),  # [0, 1] → solved
    ("A", "wrong", "wrong"),  # [0, 0] → not solved
    ("B", "grid 3", "wrong"),  # [1, 0] → solved
]


def _arc_task() -> Task:
    """The ARC-shaped Task: two any-match epochs, the per-task metric, nothing fetched."""

    return Task(
        dataset=MemoryDataset(
            [
                Sample(
                    input=f"Solve grid {index}.", target=f"grid {index}", metadata={"task_id": task}
                )
                for index, (task, _, _) in enumerate(_ARC_GRIDS, start=1)
            ]
        ),
        scorer=grid_match(),
        metrics=[per_task_accuracy()],
        epochs=Epochs(2, ["max", "pass_at_2"]),
    )


def _arc_benchmark(key: str, row: BenchmarkSpec) -> ImportedBenchmark:
    """The plugin Benchmark a reviewed row assembles into: its scorer, metric and reducer
    resolved from the row's own references, as assembly does."""

    return single_shot_benchmark(
        benchmark_key=key,
        title="Grid solving",
        description="An ARC-shaped stand-in.",
        focus="Reasoning",
        dataset_url="https://example.test/grids",
        case_count=len(_ARC_GRIDS),
        revision_pins=("stand-in",),
        scorer_factory=benchmarks._scorer_factory(row),
        prepare=lambda out: {},
        install=lambda node, assets: None,
        with_check_surface=False,
        difficulty="hard",
        whole_run_metric_factory=benchmarks._whole_run_metric_factory(row),
        epoch_reducer_factory=benchmarks._epoch_reducer_factory(row),
        attempts=row.attempts,
    )


async def _aggregate_attempts(
    benchmark: ImportedBenchmark, root: Path, grids: list[tuple[str, str, str]]
) -> dict[str, Any]:
    """Grade each grid's two Attempts through the plugin's own aggregate, one Attempts row
    per Case, as the run hands them over."""

    _write_cases(
        [
            {
                "case": {"id": index, "case_id": str(index), "input": f"Solve grid {index}."},
                "grading_material": {"target": f"grid {index}", "metadata": {"task_id": task}},
            }
            for index, (task, _, _) in enumerate(grids, start=1)
        ],
        root,
    )
    rows: str = json.dumps(
        [
            {
                "schema": CASE_ATTEMPTS_SCHEMA,
                "case_id": index,
                "attempts": [_row(index, first), _row(index, second)],
            }
            for index, (_, first, second) in enumerate(grids, start=1)
        ]
    )
    return await benchmark_aggregate_async(
        benchmark, rows, root, case_ids=tuple(range(1, len(grids) + 1))
    )


@pytest.mark.asyncio
async def test_an_arc_shaped_task_imports_with_honour_and_scores_per_task(tmp_path: Path) -> None:
    """Worked example: task A has 2 grids, 1 solved → 0.5; task B has 1 grid, solved → 1.0.
    The per-task average is (0.5 + 1.0) / 2 = 0.75, ARC's number; the per-grid mean, 2 / 3 =
    0.667, is what the mean would publish. Grid 1 is solved by Attempt 2 only ([0, 1]) and
    grid 3 by Attempt 1 only ([1, 0]); both count, through the Task's own ``max``."""

    # Stage 1 — import: any-of-2 epochs become 2 Attempts, and the row names the reducer.
    facts: TaskReplayFacts = _facts_of(
        _arc_task(), sys.modules[__name__], f"{__name__}:arc_task", None, False, "honour"
    )
    _, row = _rendered_row(facts)
    assert (row.attempts, row.epoch_reducer) == (2, "max")
    assert row.whole_run_metric == f"TODO:{__name__}:per_task_accuracy"
    # Stage 2 — a reviewer confirms the metric is higher-is-better up to 1.
    reviewed: BenchmarkSpec = replace(
        row, whole_run_metric=str(row.whole_run_metric).removeprefix("TODO:")
    )

    # Stage 3 — the run: three grids, two Attempts each.
    result: dict[str, Any] = await _aggregate_attempts(
        _arc_benchmark("arc-shaped", reviewed), tmp_path, _ARC_GRIDS
    )

    assert [case["grade"]["score"] for case in result["cases"]] == [1.0, 0.0, 1.0]
    assert result["score"] == 0.75


@pytest.mark.asyncio
@pytest.mark.parametrize("reducer", ["max", "pass_at_2"])
async def test_a_case_whose_attempt_failed_reaches_the_metric_only_if_the_reducer_agrees(
    tmp_path: Path, reducer: str
) -> None:
    """Grid 1's Attempt 1 is solved and its Attempt 2 fails (the scorer raises). The fold
    credits grid 1 from the one graded Attempt: 1.0. ``max`` over that one Score agrees.
    ``pass_at(2)`` over one Score is undefined, and inspect itself reduces it to nan; the
    tally refuses by name rather than hand the metric a number the Case Result does not show.
    """

    row: BenchmarkSpec = replace(
        _spec("aime24"),
        scorer=f"{__name__}:grid_match",
        scorer_kwargs={},
        whole_run_metric=f"{__name__}:per_task_accuracy",
        attempts=2,
        epoch_reducer=reducer,
    )
    benchmark: ImportedBenchmark = _arc_benchmark(f"arc-failed-attempt-{reducer}", row)
    grids: list[tuple[str, str, str]] = [("A", "grid 1", "crash")]

    if reducer == "max":
        result: dict[str, Any] = await _aggregate_attempts(benchmark, tmp_path, grids)
        assert result["score"] == 1.0
        return
    with pytest.raises(
        AggregateError,
        match=r"Case 1's Attempts reduce to nan for per_task_accuracy, but fold to 1.0",
    ):
        await _aggregate_attempts(benchmark, tmp_path, grids)


# ── 4. the row ───────────────────────────────────────────────────────────────────────────


def test_no_published_row_opts_in_so_no_revision_moves() -> None:
    """INVARIANT: honouring the eval's metric is a per-Benchmark owner decision, never a
    default; test_published_revisions pins the revisions this keeps still.

    The rows that opt in, each by name, each an owner decision: contracteval (OME-1527, Work
    order #7: its hand-built headline was always the run's F1), ARC-AGI-2 (OME-1476: its
    headline averages per task, not per grid) and ifeval (OME-1527, Work order #15: its
    hand-built instruction-level accuracy was always pooled over the run's instructions). Any
    other row joining this list is a new owner decision and must be named here."""

    opted_in: list[str] = [spec.key for spec in BENCHMARKS if spec.whole_run_metric is not None]
    assert opted_in == ["arc_agi_2", "contracteval", "ifeval"]
    assert all(
        benchmarks._whole_run_metric_pins(spec) == ()
        for spec in BENCHMARKS
        if spec.key not in opted_in
    )


def _spec(key: str = "gsm8k", **overrides: Any) -> BenchmarkSpec:
    """A real row (gsm8k's unless named) with overrides; the benchmark caches are patched per
    test. gsm8k drops its Sample metadata; aime24 keeps it."""

    row: BenchmarkSpec = next(spec for spec in BENCHMARKS if spec.key == key)
    return replace(row, **overrides)


def _assembled(spec: BenchmarkSpec, monkeypatch: pytest.MonkeyPatch) -> ImportedBenchmark:
    monkeypatch.setattr(benchmarks, "BENCHMARKS", (spec,))
    monkeypatch.setattr(benchmarks, "_ASSEMBLED", {})
    monkeypatch.setattr(single_shot, "_BENCHMARKS_BY_ID", {})
    return benchmarks.imported_benchmark(spec.key)


def test_naming_a_metric_is_benchmark_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    # WHY aime24: a row honouring a metric must keep its Sample metadata, and aime24 does.
    plain: str = _assembled(_spec("aime24"), monkeypatch).benchmark.revision
    honoured: ImportedBenchmark = _assembled(
        _spec("aime24", whole_run_metric="inspect_evals.hle.metrics:accuracy"), monkeypatch
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


def test_a_metric_beside_attempts_assembles_with_the_tasks_reducer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WHY allowed (OME-1527 x OME-1458): the metric reads each Case's Attempt Scores reduced
    by the Task's own any-of-N reducer, as inspect does, so Attempts rewrite nothing it reads.
    The reducer is identity: it decides the number the metric reads per Case."""

    spec: BenchmarkSpec = _spec(
        "aime24",
        whole_run_metric="inspect_evals.hle.metrics:accuracy",
        attempts=2,
        epoch_reducer="max",
    )

    honoured: ImportedBenchmark = _assembled(spec, monkeypatch)

    assert honoured.epoch_reducer_factory is not None
    assert reducer_log_names([honoured.epoch_reducer_factory()]) == ["max"]
    assert "epoch_reducer=max" in benchmarks._whole_run_metric_pins(spec)


@pytest.mark.parametrize(
    ("overrides", "words"),
    [
        # The row cannot say which reducer inspect would run, so the metric's input is unknown.
        ({"attempts": 2}, "needs the Task's own epoch_reducer, one of at_least_1, max, pass_at_2"),
        # mean at N is an average, not any-of-N; task_attempts refuses it at import too.
        ({"attempts": 2, "epoch_reducer": "mean"}, "got 'mean'"),
        # pass_at_1 at N=2 is inspect's unbiased estimator, a different number.
        ({"attempts": 2, "epoch_reducer": "pass_at_1"}, "got 'pass_at_1'"),
    ],
)
def test_a_metric_beside_attempts_needs_an_any_of_n_reducer(
    monkeypatch: pytest.MonkeyPatch, overrides: Mapping[str, Any], words: str
) -> None:
    spec: BenchmarkSpec = _spec(
        "aime24", whole_run_metric="inspect_evals.hle.metrics:accuracy", **overrides
    )

    with pytest.raises(ValueError, match=f"aime24: whole_run_metric with attempts=2 .*{words}"):
        _assembled(spec, monkeypatch)


def test_a_reducer_nothing_reads_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """WHY: only the honoured metric reads the reducer; on any other row it would move the
    revision while changing no number."""

    with pytest.raises(ValueError, match="aime24: epoch_reducer is read only by"):
        _assembled(_spec("aime24", attempts=2, epoch_reducer="max"), monkeypatch)


def test_a_metric_on_a_row_that_drops_sample_metadata_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WHY: gsm8k was imported without its Sample metadata, so a metric reading it would see
    an empty dict, and one written with ``.get(key, default)`` would publish a wrong number.
    A hand edit adding the metric is refused; re-importing with honour keeps the metadata."""

    spec: BenchmarkSpec = _spec(whole_run_metric="inspect_evals.hle.metrics:accuracy")

    with pytest.raises(ValueError, match="gsm8k: whole_run_metric needs keep_sample_metadata"):
        _assembled(spec, monkeypatch)


def test_an_unreviewed_metric_never_ships(monkeypatch: pytest.MonkeyPatch) -> None:
    """The importer writes an honoured metric as ``TODO:<reference>``; only a reviewer who has
    confirmed it is higher-is-better up to 1 deletes the prefix."""

    spec: BenchmarkSpec = _spec(whole_run_metric="TODO:inspect_evals.xstest.xstest:refusal_rate")

    with pytest.raises(ValueError, match="gsm8k: whole_run_metric is unreviewed"):
        _assembled(spec, monkeypatch)


# ── 5. a dict metric: the row names its headline, the other keys become run metrics ──────


@metric
def clause_report() -> Metric:
    """contracteval's shape: F1 as a dict key beside precision, recall and a count, all over
    the run's confusion matrix (``has_clause`` read from the Sample metadata, as clause_f1)."""

    def compute(scores: list[SampleScore]) -> dict[str, float | int]:
        cells: dict[str, int] = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
        for sample in scores:
            has_clause: bool = bool((sample.sample_metadata or {})["has_clause"])
            said_none: bool = _NONE in str(sample.score.answer)
            if has_clause:
                cells["tp" if not said_none else "fn"] += 1
            else:
                cells["fp" if not said_none else "tn"] += 1
        precision: float = cells["tp"] / (cells["tp"] + cells["fp"])
        recall: float = cells["tp"] / (cells["tp"] + cells["fn"])
        return {
            "f1": 2 * precision * recall / (precision + recall),
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "true_negatives": cells["tn"],
        }

    return compute


@metric
def nan_precision() -> Metric:
    """A dict whose extra number is not finite."""

    def compute(scores: list[SampleScore]) -> dict[str, float]:
        return {"f1": 0.5, "precision": float("nan")}

    return compute


@metric
def worded_label() -> Metric:
    """A dict whose extra value is a word, not a number."""

    def compute(scores: list[SampleScore]) -> dict[str, float | str]:
        return {"f1": 0.5, "label": "high"}

    return compute


@metric
def own_correct() -> Metric:
    """A dict reusing a key the tally already publishes (``correct``)."""

    def compute(scores: list[SampleScore]) -> dict[str, float | int]:
        return {"f1": 0.5, "correct": 99}

    return compute


@metric
def percent_f1() -> Metric:
    """A dict whose headline is a percent, which no Headline Score may be."""

    def compute(scores: list[SampleScore]) -> dict[str, float]:
        return {"f1": 50.0, "recall": 0.5}

    return compute


def _dict_benchmark(
    key: str, metric_factory: Callable[[], Any], headline: str | None
) -> ImportedBenchmark:
    """The clause stand-in Benchmark with a whole-run metric and the row's headline key."""

    return single_shot_benchmark(
        benchmark_key=key,
        title="Clause finding",
        description="A contracteval-shaped stand-in.",
        focus="Contracts",
        dataset_url="https://example.test/contracts",
        case_count=10,
        revision_pins=("stand-in",),
        scorer_factory=clause_match,
        prepare=lambda out: {},
        install=lambda node, assets: None,
        with_check_surface=False,
        difficulty="easy",
        whole_run_metric_factory=metric_factory,
        whole_run_headline=headline,
    )


@pytest.mark.asyncio
async def test_a_dict_metric_publishes_the_named_headline_and_the_rest_as_run_metrics(
    tmp_path: Path,
) -> None:
    """Worked example, 10 Cases (3 with a clause): two clauses found, one missed by declining,
    five rightful declines and two quotes where no clause exists → TP 2, FN 1, TN 5, FP 2;
    precision 2/4 = 0.5, recall 2/3 = 0.6667, F1 = 2·0.5·0.6667 / 1.1667 = 0.5714.

    INVARIANT: precision and recall land in the run's ``metrics``, never as Named Scores (no
    Case has a precision), and beside the tally's own ``correct`` and ``scored_cases``: 2
    found + 5 declines are the 7 Cases ``clause_match`` marked 1."""

    answers: list[str] = ["clause 1", "clause 2", _NONE] + [_NONE] * 5 + ["clause 9", "clause 10"]

    result: dict[str, Any] = await _aggregate(
        _dict_benchmark("clause-report", clause_report, "f1"),
        tmp_path,
        _SEVENTY_PERCENT_NONE,
        answers,
    )

    assert result["score"] == 0.5714
    assert result["metrics"] == {
        "correct": 7,
        "scored_cases": 10,
        "precision": 0.5,
        "recall": 0.6667,
        "true_negatives": 5,
    }
    assert not result.get("scores")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("key", "factory", "headline", "words"),
    [
        # The row never said which key is the headline, so any pick would be a guess.
        (
            "clause-dict-no-headline",
            clause_counts,
            None,
            r"clause_counts returned a dict \(found_rate, cases\); name the key that is the "
            r"Headline Score with the row's whole_run_headline",
        ),
        # The row names a key the metric does not return: a stale or mistyped declaration.
        (
            "clause-dict-missing-key",
            clause_counts,
            "f1",
            r"clause_counts returned a dict \(found_rate, cases\) with no 'f1'",
        ),
        # A nan run metric would read as a number beside the headline.
        ("clause-dict-nan", nan_precision, "f1", "nan_precision returned precision=nan"),
        ("clause-dict-word", worded_label, "f1", "worded_label returned label='high'"),
        # The tally's own count of the Cases it saw is never overwritten.
        (
            "clause-dict-collision",
            own_correct,
            "f1",
            "own_correct returned correct, which the tally already publishes",
        ),
        # The named headline keeps every check a number headline has.
        ("clause-dict-percent", percent_f1, "f1", "percent_f1 returned 50.0"),
        # A number on a row that says the metric returns a dict: one of the two is wrong.
        ("clause-number-with-key", found_rate, "f1", "drop whole_run_headline"),
    ],
)
async def test_a_dict_metric_the_row_cannot_publish_faithfully_is_refused_by_name(
    tmp_path: Path, key: str, factory: Callable[[], Any], headline: str | None, words: str
) -> None:
    with pytest.raises(AggregateError, match=words):
        await _aggregate(
            _dict_benchmark(key, factory, headline), tmp_path, [True] * 2, ["clause 1"] * 2
        )


def test_a_headline_key_without_a_metric_is_refused_at_assembly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WHY: the key names a number of the metric's dict; on a row keeping the mean it would
    move the revision while changing no number."""

    with pytest.raises(ValueError, match="aime24: whole_run_headline names a key"):
        _assembled(_spec("aime24", whole_run_headline="f1"), monkeypatch)


def test_a_headline_key_is_benchmark_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """WHY: the key decides which of the dict's numbers is the published headline, so naming
    another key must never keep a revision its published scores hang off."""

    honoured: BenchmarkSpec = _spec("aime24", whole_run_metric="inspect_evals.hle.metrics:accuracy")
    plain: str = _assembled(honoured, monkeypatch).benchmark.revision
    keyed: ImportedBenchmark = _assembled(replace(honoured, whole_run_headline="f1"), monkeypatch)

    assert keyed.benchmark.revision != plain
    assert keyed.whole_run_headline == "f1"
    assert benchmarks._whole_run_metric_pins(replace(honoured, whole_run_headline="f1")) == (
        "whole_run_metric=inspect_evals.hle.metrics:accuracy",
        "whole_run_headline=f1",
    )
