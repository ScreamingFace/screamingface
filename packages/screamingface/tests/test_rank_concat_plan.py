"""sf.Rank and sf.Concat compile through the reducer plan seam (OME-1289 gap, unit 10S, B#1)."""

from __future__ import annotations

import pytest
from _combine_flow_fixtures import RUBRIC

import screamingface as sf
from screamingface._evaluation.candidate import _selection_label
from screamingface.reducer import Reducer, _Step, _Steps


def _scores_judge() -> sf.Judge:
    return sf.Judge("provider/j", returns="scores", rubric=RUBRIC)


def test_rank_and_concat_build_a_reducer_plan() -> None:
    judge = _scores_judge()
    by_judge = sf.Rank(2, by=judge)._plan()
    by_field = sf.Rank(2, by_field="score")._plan()
    concat = sf.Concat("|", label=False)._plan()

    # Rank by a judge reads the judge call through the plan, as a Vote with a judge does
    assert (by_judge.reducer, by_judge.kind) == ("rank", "selection")
    assert by_judge.signal_calls == (judge._signal_call(),)
    assert by_judge.steps == _Steps(
        reduce=_Step("scores", {"source": "judge"}), select=_Step("top_k", {"k": 2})
    )
    assert (by_field.reducer, by_field.kind, by_field.signal_calls) == ("rank", "selection", ())
    assert by_field.steps == _Steps(
        extract=_Step("json_field", {"path": "score"}),
        normalize=_Step("numeric@1"),
        reduce=_Step("scores", {"source": "values"}),
        select=_Step("top_k", {"k": 2}),
    )
    assert (concat.reducer, concat.kind, concat.signal_calls) == ("concat", "selection", ())
    assert concat.steps == _Steps(
        reduce=_Step("join", {"separator": "|", "label": False}), select=_Step("all")
    )
    assert (by_judge.weights, by_judge.reads, by_judge.benchmark_rule) == (None, None, False)


def test_a_selection_label_names_the_class_or_the_block() -> None:
    assert _selection_label(sf.Rank(1, by_field="s")) == "Rank"
    assert _selection_label(sf.Concat()) == "Concat"
    assert _selection_label(sf.Reduce("concat")) == "Reduce('concat')"
    assert _selection_label(sf.Reduce("top_k", k=2, by_field="s")) == "Reduce('top_k')"


@pytest.mark.parametrize("synthesizer", [sf.Vote(), sf.Median()])
def test_an_answer_reducer_is_not_a_selection(synthesizer: Reducer) -> None:
    assert synthesizer._plan().kind == "answer"
