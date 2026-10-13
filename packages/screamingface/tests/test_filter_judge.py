"""sf.Filter(judge=...): judge pairing, refusals and url4 round trip (E4b unit 6, FJ#2-5, FJ#11).

FEATURE: ``sf.Filter(where=sf.signal("score:judge") >= 7, judge=sf.Judge(..., returns="scores"))``
keeps the members that a judge scores at or over the threshold. One judge call scores the panel.
STORY: as a benchmark author, a weak draft never reaches the writer, and a bad pairing fails when
the Filter is built, before any model call is paid.
INVARIANT defended: a ``score:judge`` comparison and a scores judge go together, a label judge or an
``order="min"`` judge never reaches a Filter, a url4 rebuilds as the same ``sf.Filter``, and the
judge rubric never appears in an error message.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from _combine_flow_fixtures import flow_operators, members3
from url4 import Expression, build

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface.reducer import Reducer
from screamingface.url4 import _calls

RUBRIC = "Score each draft."
SECRET = "SECRET-RUBRIC-TEXT"
J = sf.Judge("provider/j", returns="scores", rubric=RUBRIC)
JUDGED = sf.signal("score:judge") >= 7


def _filter_by_judge() -> sf.Filter:
    # WHY a function: the Filter is built inside each test, so a refusal fails that test and not
    # the whole module at import.
    return sf.Filter(where=JUDGED, judge=J)


def _wrapped(reducer: Reducer) -> sf.Pipeline:
    return sf.Pipeline([sf.Fusion(members3(), synthesizer=reducer), "provider/next"])


def _url4(reducer: Reducer) -> str:
    return compile_candidate(_wrapped(reducer), operators=flow_operators()).url4


def _recovered(url4: str) -> sf.Recipe:
    namespace: dict[str, Any] = {}
    exec(sf.Url4(url4).to_python(), namespace)  # noqa: S102 - our own generated code
    candidate = namespace["candidate"]
    assert isinstance(candidate, sf.Recipe)
    return candidate


# --- FJ#2: the compile adds one judge call and the signal ---------------------------------------


def test_sdk_filter_with_judge_compiles_the_judge_call_and_signal() -> None:
    url4 = _url4(_filter_by_judge())
    root = build(url4)
    assert isinstance(root, Expression)
    calls = _calls(root)
    outs = "outputs: {member_1: '$model_1', member_2: '$model_2', member_3: '$model_3'}"

    assert "judge_1" in calls
    assert calls["judge_1"].context == "{input: '$input', " + outs + "}"
    assert calls["judge_1"].prompt.splitlines()[0] == "judge-template@1 returns=scores"
    assert calls["judge_1"].prompt.endswith("Rubric:\nScore each draft.")
    assert "A higher number means a better answer." in calls["judge_1"].prompt
    assert (
        calls["synthesis_1"].context
        == "{input: '$input', " + outs + ", signals: {judge: '$judge_1'}}"
    )
    assert json.loads(calls["synthesis_1"].raw_intent) == {
        "schema": "screamingface.combine-spec.v1",
        "reducer": "filter",
        "members": ["member_1", "member_2", "member_3"],
        "extract": None,
        "normalize": None,
        "reduce": {"op": "filter@1", "args": {"key": "score:judge", "cmp": "ge", "value": 7.0}},
        "select": {"op": "kept@1", "args": {}},
        "weights": None,
    }
    # WHY one judge call for the whole panel: Q10 defers the one-call-per-member form
    assert url4.count("judge-template@1") == 1
    assert '"role":"judge"' in url4


# --- FJ-E3: a score:judge comparison needs a judge ----------------------------------------------


def test_sdk_filter_score_judge_without_judge_is_refused() -> None:
    message = (
        r"Filter where=sf\.signal\('score:judge'\) needs a judge on the same reducer: "
        r"add judge=sf\.Judge\(\.\.\., returns='scores'\)"
    )
    with pytest.raises(ValueError, match=message):
        sf.Filter(where=JUDGED)
    with pytest.raises(ValueError, match=message):
        sf.Filter(where=sf.signal("score:judge") < 3)
    with pytest.raises(
        ValueError, match=r"^sf\.Reduce\('filter'\): Filter where=.*add judge=sf\.Judge"
    ):
        sf.Reduce("filter", where=JUDGED)


# --- FJ-E4: a judge needs a score:judge comparison ----------------------------------------------


def test_sdk_filter_judge_without_score_judge_where_is_refused() -> None:
    secret = sf.Judge("provider/j", returns="scores", rubric=SECRET)
    refusal = r"Filter judge is read only by a where=sf\.signal\('score:judge'\) comparison"
    for where in (
        sf.signal("field:confidence") >= 0.6,
        sf.matches("yes"),
        sf.signal("cost_usd") <= 0.01,
    ):
        with pytest.raises(ValueError, match=refusal) as caught:
            sf.Filter(where=where, judge=secret)
        assert SECRET not in str(caught.value)

    with pytest.raises(ValueError, match=r"^sf\.Reduce\('filter'\): " + refusal) as caught:
        sf.Reduce("filter", where=sf.matches("yes"), judge=secret)
    assert SECRET not in str(caught.value)

    with pytest.raises(TypeError, match=r"Filter judge must be an sf\.Judge"):
        sf.Filter(where=JUDGED, judge="provider/j")  # type: ignore[arg-type]
    with pytest.raises(
        TypeError, match=r"sf\.Reduce\('filter'\) option 'judge' must be an sf\.Judge"
    ):
        sf.Reduce("filter", where=JUDGED, judge="provider/j")


# --- FJ-D2: a label judge or an order="min" judge is refused ------------------------------------


def test_sdk_filter_refuses_a_label_or_min_judge() -> None:
    label = sf.Judge("provider/j", returns="label", rubric=SECRET)
    low = sf.Judge("provider/j", returns="scores", rubric=SECRET, order="min")

    with pytest.raises(
        ValueError, match=r"Filter judge needs sf\.Judge\(\.\.\., returns='scores'\)"
    ) as caught:
        sf.Filter(where=JUDGED, judge=label)
    assert SECRET not in str(caught.value)

    with pytest.raises(ValueError) as caught:
        sf.Filter(where=JUDGED, judge=low)
    assert "order" in str(caught.value)
    assert SECRET not in str(caught.value)

    with pytest.raises(
        ValueError, match=r"Filter judge needs sf\.Judge\(\.\.\., returns='scores'\)"
    ):
        sf.Reduce("filter", where=JUDGED, judge=label)
    with pytest.raises(ValueError) as caught:
        sf.Reduce("filter", where=JUDGED, judge=low)
    assert "order" in str(caught.value)


# --- FJ#11: the url4 round trip rebuilds a judge Filter and the filter block --------------------


@pytest.mark.parametrize("shape", ["plain", "quorum"])
def test_url4_round_trip_rebuilds_a_judge_filter_and_filter_block(shape: str) -> None:
    if shape == "plain":
        fusion = sf.Fusion(members3(), synthesizer=_filter_by_judge())
    else:
        # WHY a quorum panel: the judge reads the panel, and the rebuild must still find its call
        fusion = sf.Fusion(
            ["provider/a", "provider/b", sf.Model("provider/c", optional=True)],
            synthesizer=_filter_by_judge(),
            quorum=2,
        )
    url4 = compile_candidate(
        sf.Pipeline([fusion, "provider/next"]), operators=flow_operators()
    ).url4

    assert (
        "synthesizer=sf.Filter(where=sf.signal('score:judge') >= 7.0, judge=sf.Judge('provider/j', "
        "returns='scores', rubric='Score each draft.'))," in sf.Url4(url4).to_python()
    )
    recovered = _recovered(url4)
    assert isinstance(recovered, sf.Pipeline)
    stage = recovered.stages[0]
    assert isinstance(stage, sf.Fusion)
    assert type(stage.synthesizer) is sf.Filter
    assert stage.synthesizer == _filter_by_judge()
    assert compile_candidate(recovered, operators=flow_operators()).url4 == url4


def test_filter_block_and_repr_rebuild_the_judge_filter() -> None:
    # WHY a separate test: the round-trip test above is already at the statement limit
    block = sf.Reduce("filter", where=JUDGED, judge=J)
    assert dict(block.options) == {"where": JUDGED, "judge": J}
    assert _url4(block) == _url4(_filter_by_judge())
    assert eval(block._python(), {"sf": sf}) == block  # noqa: S307
    recovered_block = _recovered(_url4(block))
    assert isinstance(recovered_block, sf.Pipeline)
    recovered_stage = recovered_block.stages[0]
    assert isinstance(recovered_stage, sf.Fusion)
    assert type(recovered_stage.synthesizer) is sf.Filter

    assert repr(_filter_by_judge()) == (
        "Filter(where=sf.signal('score:judge') >= 7.0, "
        "judge=Judge('provider/j', returns='scores', rubric='Score each draft.'))"
    )
    assert eval(_filter_by_judge()._python(), {"sf": sf}) == _filter_by_judge()  # noqa: S307

    # WHY a hand edit: the judge call is there, but the where no longer reads score:judge
    bad = _url4(_filter_by_judge()).replace('"key":"score:judge"', '"key":"field:confidence"')
    with pytest.raises(ValueError, match="filter spec this SDK version cannot rebuild"):
        sf.Url4(bad).to_python()
