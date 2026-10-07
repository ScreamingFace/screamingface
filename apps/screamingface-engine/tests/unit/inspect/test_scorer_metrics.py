# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""Reading a scorer's declared headline metric (OME-1268, PR 3 of 5).

FEATURE: the importer's tripwire (PR 4) refuses a Task whose Headline Score is a formula
over column means (SimpleQA's `simpleqa_metric`) rather than a plain mean, because the
reducer would otherwise publish mean(correct) as the headline. This helper is the one place
that reads a scorer's declared metrics and says "plain mean" or "other".
"""

from __future__ import annotations

import pytest

pytest.importorskip("inspect_ai")

from inspect_ai.scorer import (  # noqa: E402
    Metric,
    SampleScore,
    Score,
    Target,
    accuracy,
    exact,
    f1,
    match,
    mean,
    metric,
    scorer,
    stderr,
)
from inspect_ai.solver import TaskState  # noqa: E402

from screamingface_engine_inspect.scorer_metrics import headline_metric_kind  # noqa: E402


@metric
def harmonic_headline() -> Metric:
    """A stand-in for simpleqa_metric: a formula over the column means, not a mean."""

    def compute(scores: list[SampleScore]) -> float:
        return 0.0

    return compute


@scorer(metrics=[harmonic_headline()])
def formula_scorer():
    async def score(state: TaskState, target: Target) -> Score:
        return Score(value={"correct": 1.0})

    return score


@scorer(metrics=[accuracy(), stderr(), harmonic_headline()])
def mean_with_an_extra_metric():
    async def score(state: TaskState, target: Target) -> Score:
        return Score(value="C")

    return score


def test_inspects_own_scorers_declare_plain_means() -> None:
    assert headline_metric_kind(f1()) == "mean"
    assert headline_metric_kind(exact()) == "mean"
    assert headline_metric_kind(match()) == "mean"


def test_stderr_is_ignored() -> None:
    @scorer(metrics=[mean(), stderr()])
    def with_stderr():
        async def score(state: TaskState, target: Target) -> Score:
            return Score(value=1.0)

        return score

    assert headline_metric_kind(with_stderr()) == "mean"


def test_a_custom_headline_metric_is_other() -> None:
    assert headline_metric_kind(formula_scorer()) == "other"


def test_a_plain_mean_beside_an_extra_metric_is_still_a_mean() -> None:
    # cyberseceval_4's shape: accuracy first, grouped breakdowns beside it. The headline
    # is the first declared metric; the extras are PR 4's Named Deviation, not a refusal.
    assert headline_metric_kind(mean_with_an_extra_metric()) == "mean"


def test_a_scorer_with_no_declared_metrics_is_other() -> None:
    @scorer(metrics=[])
    def silent():
        async def score(state: TaskState, target: Target) -> Score:
            return Score(value=1.0)

        return score

    assert headline_metric_kind(silent()) == "other"
