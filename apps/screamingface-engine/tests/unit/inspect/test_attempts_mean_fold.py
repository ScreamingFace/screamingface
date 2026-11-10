# pyright: reportMissingImports=false
# WHY file-level: this suite imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""A row naming inspect's ``pass_at_1`` scores each Case as the mean of its Attempts.

FEATURE (OME-1458 amendment, ``docs/spec/2026-11-09-attempts-mean-fold.md``): ZeroBench asks
each question five times and publishes pass@1, which inspect computes with ``pass_at(1)`` over
the five epochs: c/5, the mean of the marks. The importer accepts a Task whose first declared
reducer is that one, the row carries ``epoch_reducer="pass_at_1"``, the marking room folds by
the mean, and the whole-run tally replays inspect's own reducer and checks the two agree.

INVARIANT: the Case score the Report shows is the number inspect's ``pass_at(1)`` computes over
the same Attempt Scores, on 0/1 marks and on partial marks alike. Rows that never name
``pass_at_1`` fold as before.

Runs only with the ``inspect`` extra installed. No model is called: the Candidate's replies are
stand-ins written into the Attempts rows. A look-alike ``pass_at`` (an eval's own reducer under
inspect's name) is refused in test_importer_refuses_epochs, in a child process: registering one
here would replace inspect's entry for every string lookup in this process.
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai")

from inspect_ai import Epochs, Task  # noqa: E402
from inspect_ai.dataset import MemoryDataset, Sample  # noqa: E402
from inspect_ai.scorer import (  # noqa: E402
    Metric,
    SampleScore,
    Score,
    Scorer,
    ScoreReducer,
    Target,
    accuracy,
    metric,
    score_reducer,
    scorer,
)
from inspect_ai.scorer._reducer.registry import reducer_log_names  # noqa: E402
from inspect_ai.solver import TaskState  # noqa: E402
from test_importer_whole_run_choice import _row as _rendered_row  # noqa: E402
from test_whole_run_metric import _assembled, _row, _spec  # noqa: E402

from screamingface_engine.benchmarks.graded_answer import CASE_ATTEMPTS_SCHEMA  # noqa: E402
from screamingface_engine.benchmarks.shared_grading.attempt_fold import (  # noqa: E402
    ANY_ATTEMPT_FOLD,
    MEAN_ATTEMPT_FOLD,
)
from screamingface_engine_inspect import benchmarks  # noqa: E402
from screamingface_engine_inspect.benchmarks import BenchmarkSpec  # noqa: E402
from screamingface_engine_inspect.import_replay import TaskReplayFacts, _facts_of  # noqa: E402
from screamingface_engine_inspect.importer import ImporterError, task_attempts  # noqa: E402
from screamingface_engine_inspect.prepare import _write_cases  # noqa: E402
from screamingface_engine_inspect.scorer_metrics import (  # noqa: E402
    MEAN_OVER_ATTEMPTS_REDUCER,
    attempts_reducers,
)
from screamingface_engine_inspect.single_shot import (  # noqa: E402
    ImportedBenchmark,
    benchmark_aggregate_async,
    single_shot_benchmark,
)

# ── 1. the importer: inspect's pass_at(1) headline imports as the mean over N Attempts ─────


@score_reducer(name="5_of_5_reliability")
def reliability_at_5() -> ScoreReducer:
    """Stand-in for ZeroBench's own all-of-5 reducer: right only when every epoch is right."""

    def reduce(scores: list[Score]) -> Score:
        return Score(value=1.0 if all(score.as_float() == 1.0 for score in scores) else 0.0)

    return reduce


def _task(epochs: Epochs) -> Task:
    """A one-Sample exact-match Task declaring these epochs; nothing is fetched."""

    from inspect_ai.scorer import match

    return Task(
        dataset=MemoryDataset([Sample(input="What is 6 times 7?", target="42")]),
        scorer=match(),
        epochs=epochs,
    )


def test_zerobenchs_declaration_imports_as_five_attempts_folded_by_the_mean() -> None:
    # STORY: ZeroBench declares Epochs(5, ["pass_at_1", "pass_at_5", "5_of_5_reliability"]);
    # its headline is pass_at_1, the mean over the five marks, and the other two are
    # reducers inspect also publishes that this row does not reproduce.
    read = task_attempts(_task(Epochs(5, ["pass_at_1", "pass_at_5", reliability_at_5()])))

    assert (read.attempts, read.epoch_reducer) == (5, MEAN_OVER_ATTEMPTS_REDUCER)
    assert read.dropped_reducers == ("pass_at_5", "5_of_5_reliability")


def test_pass_at_one_alone_imports_as_the_mean_with_nothing_dropped() -> None:
    read = task_attempts(_task(Epochs(5, "pass_at_1")))

    assert (read.attempts, read.epoch_reducer, read.dropped_reducers) == (5, "pass_at_1", ())


def test_an_any_of_n_task_still_imports_with_no_reducer_named() -> None:
    # INVARIANT: ARC-AGI-2's shape is untouched; the fold stays any-of-N and the row names
    # a reducer only beside an honoured whole-run metric (OME-1527), as before.
    read = task_attempts(_task(Epochs(2, "max")))

    assert (read.attempts, read.epoch_reducer, read.dropped_reducers) == (2, None, ())


def test_a_one_epoch_task_is_one_attempt_whatever_it_declares() -> None:
    assert task_attempts(_task(Epochs(1, "pass_at_1"))).attempts == 1
    assert task_attempts(_task(Epochs(1, "mode"))).epoch_reducer is None


def test_mean_beside_pass_at_one_is_still_refused_naming_mean() -> None:
    # WHY (D16): inspect's averaging reducers stay refused wherever they appear; the mean rule
    # is read only from pass_at_1 itself.
    with pytest.raises(ImporterError, match=r"epochs=5 with reducer mean"):
        task_attempts(_task(Epochs(5, ["pass_at_1", "mean"])))


def test_an_any_of_n_headline_beside_pass_at_one_is_refused_naming_pass_at_one() -> None:
    # WHY (D16): the first declared reducer is the headline; max first says the eval publishes
    # any-of-2 first and the mean beside it, two numbers a row cannot both carry.
    with pytest.raises(ImporterError, match=r"epochs=2 with reducer pass_at_1 beside .*max"):
        task_attempts(_task(Epochs(2, ["max", "pass_at_1"])))


def test_a_tuned_pass_at_one_is_refused_naming_the_threshold() -> None:
    from inspect_ai.scorer import pass_at

    with pytest.raises(ImporterError, match=r"reducer pass_at_1\(value=0\.5\)"):
        task_attempts(_task(Epochs(5, pass_at(1, value=0.5))))


def test_the_facts_and_the_row_carry_the_mean_rule_and_the_dropped_reducers() -> None:
    # Stage 1 — the facts the import child writes.
    task: Task = _task(Epochs(5, ["pass_at_1", "pass_at_5", reliability_at_5()]))
    facts: TaskReplayFacts = _facts_of(task, sys.modules[__name__], f"{__name__}:zb", None, False)
    assert (facts.attempts, facts.epoch_reducer) == (5, "pass_at_1")
    assert facts.dropped_reducers == ("pass_at_5", "5_of_5_reliability")

    # Stage 2 — the row they render says what the number means and what is left out.
    text, row = _rendered_row(facts)
    assert (row.attempts, row.epoch_reducer) == (5, "pass_at_1")
    assert "share of Attempts fully right" in text
    assert "pass_at_5, 5_of_5_reliability" in text
    assert '"mean over 5 Attempts", never "pass@1"' in text


# ── 2. assembly: the row's reducer is inspect's pass_at(1) and the fold is the mean ─────────


def test_a_mean_row_assembles_with_inspects_pass_at_one_and_no_whole_run_metric(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # WHY admitted without a metric (D17): the fold reads this reducer, so it changes the
    # published number on its own; an any-of-N name on a metric-less row stays refused.
    assembled: ImportedBenchmark = _assembled(
        _spec("aime24", attempts=5, epoch_reducer="pass_at_1"), monkeypatch
    )

    assert assembled.attempt_fold == MEAN_ATTEMPT_FOLD
    assert assembled.epoch_reducer_factory is not None
    assert reducer_log_names([assembled.epoch_reducer_factory()]) == ["pass_at_1"]


def test_an_attempts_row_without_a_reducer_folds_any_of_n_as_before(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assembled: ImportedBenchmark = _assembled(_spec("aime24", attempts=5), monkeypatch)

    assert assembled.attempt_fold == ANY_ATTEMPT_FOLD
    assert assembled.epoch_reducer_factory is None


def test_naming_the_mean_rule_is_benchmark_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    # WHY: 2/5 and 1.0 are different numbers for the same answers, so the two rules can never
    # share a revision its members' published scores hang off. The fingerprint is compared
    # because aime24's row publishes a hand-set revision (OME-1610), as the metric test does.
    any_of_five: str = _assembled(_spec("aime24", attempts=5), monkeypatch).fingerprint
    mean_of_five: str = _assembled(
        _spec("aime24", attempts=5, epoch_reducer="pass_at_1"), monkeypatch
    ).fingerprint

    assert mean_of_five != any_of_five


def test_the_mean_rule_on_a_one_attempt_row_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="aime24: epoch_reducer pass_at_1 folds Attempts"):
        _assembled(_spec("aime24", epoch_reducer="pass_at_1"), monkeypatch)


def test_every_reducer_a_row_may_name_is_built_from_inspects_own_factory() -> None:
    assert sorted(attempts_reducers(5)) == ["at_least_1", "max", "pass_at_1", "pass_at_5"]
    assert reducer_log_names([attempts_reducers(5)["pass_at_1"]]) == ["pass_at_1"]


# ── 3. the run: the Engine's fold and inspect's reducer agree, on 0/1 and partial marks ─────


@metric
def mean_of_cases() -> Metric:
    """A whole-run metric stand-in: the mean of the reduced Case Scores, so the tally runs
    and its agreement check compares inspect's pass_at(1) with the Engine's fold."""

    def compute(scores: list[SampleScore]) -> float:
        return sum(sample.score.as_float() for sample in scores) / len(scores)

    return compute


@scorer(metrics=[accuracy()])
def graded_reply() -> Scorer:
    """Stand-in scorer: full marks when the reply holds the target, half marks for a reply of
    "half", else 0. It gives the tally per-Attempt marks; it proves nothing about a judge."""

    async def score(state: TaskState, target: Target) -> Score:
        completion: str = state.output.completion
        if target.text in completion:
            return Score(value=1.0)
        return Score(value=0.5 if completion == "half" else 0.0)

    return score


def _mean_benchmark(key: str, row: BenchmarkSpec, case_count: int) -> ImportedBenchmark:
    """The plugin Benchmark a mean row assembles into, its pieces resolved as assembly does."""

    return single_shot_benchmark(
        benchmark_key=key,
        title="Mean over Attempts",
        description="A ZeroBench-shaped stand-in.",
        focus="Reasoning",
        dataset_url="https://example.test/mean",
        case_count=case_count,
        revision_pins=("stand-in",),
        scorer_factory=benchmarks._scorer_factory(row),
        prepare=lambda out: {},
        install=lambda node, assets: None,
        with_check_surface=False,
        difficulty="hard",
        failure_policy="coverage_declare",
        whole_run_metric_factory=benchmarks._whole_run_metric_factory(row),
        epoch_reducer_factory=benchmarks._epoch_reducer_factory(row),
        attempts=row.attempts,
        attempt_fold=benchmarks._attempt_fold(row),
    )


async def _aggregate(
    benchmark: ImportedBenchmark, root: Path, replies: list[list[str]]
) -> dict[str, Any]:
    """Grade each Case's Attempts (one list of replies per Case, target "42") through the
    plugin's own aggregate, one Attempts row per Case, as the run hands them over."""

    _write_cases(
        [
            {
                "case": {"id": index, "case_id": str(index), "input": "What is 6 times 7?"},
                "grading_material": {"target": "42", "metadata": {}},
            }
            for index in range(1, len(replies) + 1)
        ],
        root,
    )
    rows: str = json.dumps(
        [
            {
                "schema": CASE_ATTEMPTS_SCHEMA,
                "case_id": index,
                "attempts": [_row(index, reply) for reply in case_replies],
            }
            for index, case_replies in enumerate(replies, start=1)
        ]
    )
    return await benchmark_aggregate_async(
        benchmark, rows, root, case_ids=tuple(range(1, len(replies) + 1))
    )


def _mean_row(key: str) -> BenchmarkSpec:
    return replace(
        _spec("aime24"),
        key=key,
        scorer=f"{__name__}:graded_reply",
        scorer_kwargs={},
        whole_run_metric=f"{__name__}:mean_of_cases",
        attempts=5,
        epoch_reducer="pass_at_1",
    )


@pytest.mark.asyncio
async def test_a_case_scores_the_share_of_its_five_attempts_right_and_the_tally_agrees(
    tmp_path: Path,
) -> None:
    """Three Cases: 0, 2 and 5 right of 5. The fold scores 0.0, 0.4 and 1.0; inspect's
    pass_at(1) over the same Scores gives the same, so the tally's agreement check passes
    and the metric reads the mean, 0.4667."""

    row: BenchmarkSpec = _mean_row("mean-zero-one")
    replies: list[list[str]] = [
        ["41", "40", "43", "44", "45"],
        ["42", "41", "42", "40", "43"],
        ["42", "42", "42", "42", "42"],
    ]

    result: dict[str, Any] = await _aggregate(_mean_benchmark(row.key, row, 3), tmp_path, replies)

    assert [case["grade"]["score"] for case in result["cases"]] == [0.0, 0.4, 1.0]
    assert [len(case["attempts"]) for case in result["cases"]] == [5, 5, 5]
    assert result["score"] == round((0.0 + 0.4 + 1.0) / 3, 4)


@pytest.mark.asyncio
async def test_a_partial_attempt_counts_as_not_right_for_the_fold_and_the_reducer_alike(
    tmp_path: Path,
) -> None:
    """Marks [0.5, 1.0, 0.0, 1.0, 0.5]: inspect's pass_at(1) counts full marks only, 2/5 = 0.4,
    and so does the fold, so the two agree; a plain average, 0.6, would fail the tally."""

    row: BenchmarkSpec = _mean_row("mean-partial")
    replies: list[list[str]] = [["half", "42", "40", "42", "half"]]

    result: dict[str, Any] = await _aggregate(_mean_benchmark(row.key, row, 1), tmp_path, replies)

    case: dict[str, Any] = result["cases"][0]
    assert case["status"] == "scored"
    assert case["grade"]["score"] == 0.4
    assert [attempt["grade"]["score"] for attempt in case["attempts"]] == [0.5, 1.0, 0.0, 1.0, 0.5]
    assert result["score"] == 0.4


def test_the_mean_rule_rides_the_attempts_pins_on_a_row_with_no_whole_run_metric() -> None:
    """A row folded by the mean pins its reducer into the revision even when it honours no
    whole-run metric, and an any-of-N row beside a metric pins it where it always did.

    WHY (D17): 2/5 and 1.0 are different numbers for the same five answers, so the fold rule is
    Attempts identity; before this, a reducer was pinned only beside a whole-run metric, and a
    mean row with none (ZeroBench) would have kept its revision while changing its number.
    INVARIANT: a row honouring no metric pins nothing under the metric pins
    (test_whole_run_metric's rule), and ARC-AGI-2's revision does not move.
    """

    mean_row: BenchmarkSpec = _spec("gsm8k", attempts=5, epoch_reducer="pass_at_1")
    assert mean_row.whole_run_metric is None
    assert benchmarks._attempts_pins(mean_row) == ("attempts=5", "epoch_reducer=pass_at_1")
    assert benchmarks._whole_run_metric_pins(mean_row) == ()

    arc_row: BenchmarkSpec = next(spec for spec in benchmarks.BENCHMARKS if spec.key == "arc_agi_2")
    assert arc_row.whole_run_metric is not None
    assert benchmarks._attempts_pins(arc_row) == ("attempts=2",)
    assert "epoch_reducer=max" in benchmarks._whole_run_metric_pins(arc_row)


@pytest.mark.parametrize(("right", "refused"), [(1, 4), (2, 3)])
def test_a_silent_refusal_is_a_wrong_try_for_the_fold_and_for_inspects_reducer_alike(
    right: int, refused: int
) -> None:
    """A try the provider declined with no text counts as wrong, the way inspect scores the
    empty completion: 1 right + 4 silent refusals is 0.2, 2 right + 3 is 0.4, never 1.0.

    WHY (D15, second pass): the fold used to average over the scored Attempts only, so a
    textless refusal fell out of the denominator and one lucky try scored the Case 1.0.
    inspect's ``pass_at(1)`` over the Scores its scorer would file (a 0 for each empty
    completion) is the outside judge here.
    """

    from inspect_ai.scorer import pass_at

    from screamingface_engine.benchmarks.contract import CaseGrade, CaseResult, Check, Failure
    from screamingface_engine.benchmarks.shared_grading.attempt_fold import fold_case_attempts

    met = Check(
        type="exact_match",
        id="1",
        label="answer",
        outcome="MET",
        score=1.0,
        evidence=[],
        metadata={},
    )
    right_try = CaseResult(
        status="scored",
        case_id=1,
        input="What is 6 times 7?",
        output="42",
        finish_reason="stop",
        refusal=None,
        grade=CaseGrade(method="inspect_scorer", score=1.0, metrics={}, checks=[met]),
        failures=[],
        metadata={},
    )
    silent_refusal = CaseResult(
        status="failed",
        case_id=1,
        input="What is 6 times 7?",
        output=None,
        finish_reason=None,
        refusal=None,
        grade=None,
        failures=[
            Failure(
                stage="candidate",
                code="provider_refusal",
                message="provider refused the request",
                retryable=False,
                case_id=1,
                metadata={},
            )
        ],
        metadata={},
    )
    results: list[CaseResult] = [right_try] * right + [silent_refusal] * refused
    folded = fold_case_attempts(results, fold=MEAN_ATTEMPT_FOLD)

    inspects_view = pass_at(1)(
        [Score(value=1.0)] * right + [Score(value=0.0)] * refused  # the scorer grades "" as 0
    )
    assert folded.grade is not None
    # The tally compares the two at the Case score's 4-place rounding (1 - 4/5 is 0.19999...).
    assert folded.grade.score == round(inspects_view.as_float(), 4) == right / (right + refused)
