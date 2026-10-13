"""Filter by a judge score: the threshold on score:judge, its evidence, its refusals (E4b unit 6).

FEATURE: ``sf.Filter(where=sf.signal("score:judge") >= 7, judge=...)`` keeps the members
that a judge scores at or over the threshold. The next stage gets the Case input and the kept
members.
STORY: as a benchmark author, a weak draft never reaches the writer, and a judge reply that cannot
be read fails the Case instead of keeping every member.
INVARIANT defended: the threshold passes its boundary (7 at ``>= 7``); a Case with no passing member
abstains with ``no_votes``; a bad judge reply fails permanently with ``judge_reply_invalid`` and is
never echoed; the judge scores only the panel; ``<`` keeps the low scores. These are CHAR tests:
``filter@1`` already reads ``score:judge`` from the judge reply, and the Engine does not change.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from combine_signal_support import filter_spec
from combine_support import context_text, request, run, spec_text

from screamingface_engine.combine import ports
from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.combine.evidence import ResultRecord, SignalRecord
from screamingface_engine.combine.ports import CombineError
from screamingface_engine.operation_calls import capture_operation_calls
from screamingface_engine.world.combine import CombineRoute
from url4.core.errors import ResolutionError

_TEXTS = ["alpha draft", "beta draft", "gamma draft"]
_REPLY = '{"member_1": 9, "member_2": 4, "member_3": 7}'
_KEY = "score:judge"


def _spec(cmp: str, value: float = 7.0, n: int = 3) -> dict[str, Any]:
    return filter_spec(n, {"key": _KEY, "cmp": cmp, "value": value})


def _run(cmp: str, reply: str) -> Any:
    return run(
        spec_text(_spec(cmp)),
        context_text(_TEXTS, {"judge": reply}),
        registry=BUILTIN_OPERATORS,
    )


def _panel_rows(texts: dict[int, str]) -> str:
    """The broadcast rows url4 writes for the members that answered (1-based positions)."""
    return json.dumps(
        [
            {"source_position": index, "source_name": f"member_{index}", "result": answer}
            for index, answer in texts.items()
        ]
    )


def _panel_context(texts: dict[int, str], **extra: Any) -> str:
    return json.dumps({"input": "q", "panel": _panel_rows(texts), **extra})


# --- FJ-1 (engine half): the threshold keeps the members at or over it ----------------------------


def test_engine_filter_threshold_on_score_judge_keeps_passing_members() -> None:
    outcome = _run("ge", _REPLY)

    assert outcome.output == (
        '{"input":"q","selected":[{"id":"member_1","text":"alpha draft"},'
        '{"id":"member_3","text":"gamma draft"}]}'
    )
    # WHY member_3 is kept: 7 at ">= 7" is on the boundary, and the boundary passes
    assert outcome.evidence.chosen == ["member_1", "member_3"]


# --- FJ-2: the evidence names the signal, the values and the pass marks ---------------------------


def test_engine_filter_by_judge_evidence_has_signal_values_and_marks() -> None:
    evidence = _run("ge", _REPLY).evidence

    assert [m.signals for m in evidence.members] == [
        {"score:judge": 9.0},
        {"score:judge": 4.0},
        {"score:judge": 7.0},
    ]
    assert [m.score for m in evidence.members] == [1.0, 0.0, 1.0]
    assert evidence.signal == SignalRecord(key="score:judge", order=None)
    # WHY None: the raw judge reply lives in the judge's own operation record (op_judge_N)
    assert evidence.judge is None
    assert evidence.presentation_order == "author"
    assert (evidence.kind, evidence.reducer, evidence.built) == ("selection", "filter", True)
    assert evidence.result == ResultRecord(
        member_id=None, value=None, status="answered", reason=None
    )
    assert evidence.dropped == 0


# --- FJ-E1: no passing member abstains (Q4: no fallback) -----------------------------------------


def test_engine_filter_by_judge_with_no_pass_abstains() -> None:
    outcome = _run("ge", '{"member_1": 2, "member_2": 4, "member_3": 6.5}')

    assert outcome.output == ""
    assert outcome.evidence.result == ResultRecord(
        member_id=None, value=None, status="abstain", reason="no_votes"
    )
    assert outcome.evidence.chosen == []
    assert outcome.evidence.built is False
    assert [m.score for m in outcome.evidence.members] == [0.0, 0.0, 0.0]
    assert [m.signals["score:judge"] for m in outcome.evidence.members] == [2.0, 4.0, 6.5]


# --- FJ-E2: a bad judge reply fails the Case, it does not abstain --------------------------------


@pytest.mark.parametrize(
    "reply",
    [
        "I like member 1",
        '{"member_1": 9, "member_2": 4}',
        '{"member_1": 9, "member_2": 4, "member_3": NaN}',
    ],
    ids=["prose", "missing", "nan"],
)
def test_engine_filter_by_judge_with_invalid_reply_fails_permanently(reply: str) -> None:
    with pytest.raises(CombineError) as caught:
        _run("ge", reply)
    assert caught.value.code == "judge_reply_invalid"
    # WHY the whole message is the fixed rule text: it can never repeat the judge reply
    assert str(caught.value) == ports._SCORES_INVALID

    with capture_operation_calls() as calls:
        with pytest.raises(ResolutionError) as resolved:
            CombineRoute(BUILTIN_OPERATORS)(
                request(spec_text(_spec("ge")), context_text(_TEXTS, {"judge": reply}))
            )
    assert resolved.value.permanent is True
    assert list(calls) == []


# --- FJ-D1: a quorum panel drops the member the judge did not see ---------------------------------


def test_engine_filter_by_judge_drops_a_missing_panel_member() -> None:
    context = _panel_context(
        {1: "alpha draft", 3: "gamma draft"},
        signals={"judge": '{"member_1": 9, "member_3": 8}'},
    )

    outcome = run(spec_text(_spec("ge")), context, registry=BUILTIN_OPERATORS)

    assert outcome.output == (
        '{"input":"q","selected":[{"id":"member_1","text":"alpha draft"},'
        '{"id":"member_3","text":"gamma draft"}]}'
    )
    assert outcome.evidence.chosen == ["member_1", "member_3"]
    missing = outcome.evidence.members[1]
    assert (missing.status, missing.reason, missing.score, missing.signals) == (
        "fail",
        "missing",
        None,
        {"score:judge": None},
    )
    assert outcome.evidence.dropped == 1

    # WHY the reply that also scores member_2 fails: the judge saw only the panel
    with pytest.raises(CombineError) as caught:
        run(
            spec_text(_spec("ge")),
            _panel_context(
                {1: "alpha draft", 3: "gamma draft"},
                signals={"judge": '{"member_1": 9, "member_2": 8, "member_3": 8}'},
            ),
            registry=BUILTIN_OPERATORS,
        )
    assert caught.value.code == "judge_reply_invalid"


# --- FJ-D4 (N1): "<" keeps the low scores ---------------------------------------------------------


def test_engine_filter_by_judge_less_than_keeps_low_scores() -> None:
    outcome = _run("lt", _REPLY)

    assert outcome.output == '{"input":"q","selected":[{"id":"member_2","text":"beta draft"}]}'
    assert outcome.evidence.chosen == ["member_2"]
    # WHY member_3 is dropped: 7 < 7 is false
    assert [m.score for m in outcome.evidence.members] == [0.0, 1.0, 0.0]
