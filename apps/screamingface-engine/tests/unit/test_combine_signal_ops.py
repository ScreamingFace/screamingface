"""Argmax, rank by a signal and a filter run on named signals (OME-1289 E4a gap-closure, unit 10E).

FEATURE: a spec ranks or filters members by one signal (an accounting number, a ``field:`` number)
with no model call and no rewrite of a member text.
STORY: as a researcher, "the cheapest member's answer" and "the members that are at least 60%
sure" are enforced by the engine, the same way on every replay.
INVARIANT defended: only a member that answered is ranked or picked (F4); a missing signal abstains
with ``no_votes``, a cut that cannot be met with ``cut_not_met``; a tie goes to author order; the
evidence records the signal key, its order and each member's number.
"""

from __future__ import annotations

from typing import Any

import pytest
from combine_signal_support import argmax_spec, costs, filter_spec, sources
from combine_support import context_text, run, spec_text

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.combine.evidence import ResultRecord, SignalRecord
from screamingface_engine.combine.ports import CombineError, canonical_json


def _field_texts(values: list[Any], name: str = "s") -> list[str]:
    return [canonical_json({name: value}) for value in values]


def _argmax_field(values: list[Any], order: str) -> Any:
    return run(
        spec_text(argmax_spec(len(values), "field:s", order)),  # type: ignore[arg-type]
        context_text(_field_texts(values)),
        registry=BUILTIN_OPERATORS,
    )


def _failure(spec: dict[str, Any], texts: list[str], **context: Any) -> CombineError:
    with pytest.raises(CombineError) as caught:
        run(spec_text(spec), context_text(texts, **context), registry=BUILTIN_OPERATORS)
    return caught.value


# --- SR#5 -------------------------------------------------------------------------------------


def test_argmax_min_returns_cheapest_member_text_as_answer() -> None:
    outcome = run(
        spec_text(argmax_spec(3, "cost_usd", "min")),
        context_text(["A", "B", "C"], sources=sources(3)),
        registry=BUILTIN_OPERATORS,
        accounting=costs(0.004, 0.001, 0.002),
    )

    evidence = outcome.evidence
    assert outcome.output == "B"
    assert evidence.chosen == ["member_2"]
    assert evidence.result == ResultRecord(
        member_id="member_2", value=None, status="answered", reason=None
    )
    assert (evidence.kind, evidence.reducer, evidence.built) == ("answer", "pick", False)
    assert evidence.signal == SignalRecord(key="cost_usd", order="min")
    assert [m.score for m in evidence.members] == [0.004, 0.001, 0.002]


def test_argmax_compares_signed_field_values_as_they_are() -> None:
    values = [-3, -1, 2]

    lowest, highest = _argmax_field(values, "min"), _argmax_field(values, "max")

    assert lowest.evidence.chosen == ["member_1"]
    assert highest.evidence.chosen == ["member_3"]
    assert [m.score for m in lowest.evidence.members] == [-3.0, -1.0, 2.0]


# --- SR#12 ------------------------------------------------------------------------------------


def test_by_signal_rejects_bad_args_without_echoing_the_key() -> None:
    spec = argmax_spec(3, "cost_usd", "max")
    spec["reduce"] = {"op": "by_signal@1", "args": {"key": "logprob_mean", "order": "max"}}

    failure = _failure(spec, ["A", "B", "C"], sources=sources(3))

    assert failure.code == "combine_spec_invalid"
    assert "by_signal@1 args are invalid" in str(failure)
    assert "logprob_mean" not in str(failure)


# --- FL#1 to FL#5, FL#10 ----------------------------------------------------------------------

_CONFIDENCE = "field:confidence"


def _filter(args: dict[str, Any], texts: list[str], extract: Any = None) -> Any:
    return run(
        spec_text(filter_spec(len(texts), args, extract)),
        context_text(texts),
        registry=BUILTIN_OPERATORS,
    )


_PATTERN = {"pattern": "ANSWER: \\d+"}


def test_filter_evidence_records_values_chosen_and_dropped() -> None:
    texts = [
        canonical_json({"answer": "a", "confidence": 0.9}),
        "not json at all",
        canonical_json({"answer": "c", "confidence": 0.7}),
        canonical_json({"answer": "d", "confidence": 0.2}),
    ]
    extract = {"op": "json_field@1", "args": {"path": "answer"}}

    outcome = _filter({"key": _CONFIDENCE, "cmp": "ge", "value": 0.6}, texts, extract)

    evidence = outcome.evidence
    assert evidence.dropped == 1
    assert (evidence.members[1].status, evidence.members[1].reason) == ("fail", "not_json")
    assert [m.score for m in evidence.members] == [1.0, None, 1.0, 0.0]
    assert [m.signals[_CONFIDENCE] for m in evidence.members] == [0.9, None, 0.7, 0.2]
    assert evidence.chosen == ["member_1", "member_3"]
    assert (evidence.kind, evidence.reducer, evidence.built) == ("selection", "filter", True)
    assert evidence.result == ResultRecord(
        member_id=None, value=None, status="answered", reason=None
    )
    assert evidence.signal == SignalRecord(key=_CONFIDENCE, order=None)


def test_filter_envelope_over_output_cap_fails_input_too_large() -> None:
    texts = ["x" * (1024 * 1024 - 9) + "ANSWER: 1"] * 9

    failure = _failure(filter_spec(9, _PATTERN), texts)

    assert failure.code == "combine_input_too_large"
