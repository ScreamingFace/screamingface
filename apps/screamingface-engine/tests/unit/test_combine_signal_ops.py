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
from combine_signal_support import argmax_spec, costs, rank_signal_spec, sources
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


def _abstain(reason: str) -> ResultRecord:
    return ResultRecord(member_id=None, value=None, status="abstain", reason=reason)  # type: ignore[arg-type]


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
    assert [m.score for m in evidence.members] == [0.004, 0.001, 0.002]


def test_argmax_compares_signed_field_values_as_they_are() -> None:
    values = [-3, -1, 2]

    lowest, highest = _argmax_field(values, "min"), _argmax_field(values, "max")

    assert lowest.evidence.chosen == ["member_1"]
    assert highest.evidence.chosen == ["member_3"]
    assert [m.score for m in lowest.evidence.members] == [-3.0, -1.0, 2.0]


# --- SR#6 -------------------------------------------------------------------------------------


def test_missing_argmax_signal_is_not_ranked_and_short_cut_abstains() -> None:
    texts = [canonical_json({"s": 3}), canonical_json({"t": 1}), canonical_json({"s": 1})]
    spec = argmax_spec(3, "field:s", "max")
    partial = run(spec_text(spec), context_text(texts), registry=BUILTIN_OPERATORS)
    assert partial.evidence.chosen == ["member_1"]
    assert [m.score for m in partial.evidence.members] == [3.0, None, 1.0]
    lowest = run(
        spec_text(argmax_spec(3, "field:s", "min")), context_text(texts), registry=BUILTIN_OPERATORS
    )
    assert lowest.evidence.chosen == ["member_3"]

    # A member that failed is never ranked, even when it holds a number (F4).
    big = "x" * (1024 * 1024 + 1)
    cheap = run(
        spec_text(argmax_spec(3, "cost_usd", "min")),
        context_text(["A", big, "C"], sources=sources(3)),
        registry=BUILTIN_OPERATORS,
        accounting=costs(0.5, 0.001, 0.2),
    )
    assert cheap.evidence.chosen == ["member_3"]
    assert [(m.status, m.reason) for m in cheap.evidence.members][1] == ("fail", "too_large")
    assert [m.signals for m in cheap.evidence.members][1] == {"cost_usd": 0.001}
    assert [m.score for m in cheap.evidence.members] == [0.5, None, 0.2]

    # No member has the signal: the step abstains and no row has a score.
    none = _argmax_field_missing()
    assert none.output == ""
    assert none.evidence.result == _abstain("no_votes")
    assert [m.score for m in none.evidence.members] == [None, None, None]
    assert none.evidence.chosen == []

    # A rank of three over two ranked members is a cut that cannot be met.
    short = run(
        spec_text(rank_signal_spec(3, 3, "field:s", "max")),
        context_text(_field_texts([1, None, 2])),
        registry=BUILTIN_OPERATORS,
    )
    assert short.output == ""
    assert short.evidence.result == _abstain("cut_not_met")
    assert [m.score for m in short.evidence.members] == [1.0, None, 2.0]


def _argmax_field_missing() -> Any:
    return run(
        spec_text(argmax_spec(3, "field:s", "max")),
        context_text(_field_texts([None, "x", True], "t")),
        registry=BUILTIN_OPERATORS,
    )


# --- SR#7 -------------------------------------------------------------------------------------


def test_signal_ties_go_to_author_order() -> None:
    highest = _argmax_field([0.9, 0.5, 0.9], "max")
    assert highest.evidence.chosen == ["member_1"]
    assert highest.evidence.tie is True

    lowest = _argmax_field([0.2, 0.2, 0.5], "min")
    assert lowest.evidence.chosen == ["member_1"]
    assert lowest.evidence.tie is True

    clear = _argmax_field([0.2, 0.1, 0.5], "min")
    assert clear.evidence.chosen == ["member_2"]
    assert clear.evidence.tie is False


# --- SR#8 -------------------------------------------------------------------------------------


def test_rank_by_signal_keeps_top_k_in_order() -> None:
    values = [0.3, 0.9, 0.5, 0.7]
    texts = _field_texts(values, "score")

    outcome = run(
        spec_text(rank_signal_spec(4, 2, "field:score", "max")),
        context_text(texts),
        registry=BUILTIN_OPERATORS,
    )

    expected = canonical_json(
        {
            "selected": [
                {"id": "member_2", "text": texts[1]},
                {"id": "member_4", "text": texts[3]},
            ]
        }
    )
    assert outcome.output == expected
    assert outcome.evidence.kind == "selection"
    assert outcome.evidence.chosen == ["member_2", "member_4"]
    assert outcome.evidence.operators == ["by_signal@1", "top_k@1"]

    lowest = run(
        spec_text(rank_signal_spec(4, 2, "field:score", "min")),
        context_text(texts),
        registry=BUILTIN_OPERATORS,
    )
    assert lowest.evidence.chosen == ["member_1", "member_3"]


# --- SR#12 ------------------------------------------------------------------------------------


def test_evidence_records_signal_key_order_and_values() -> None:
    outcome = run(
        spec_text(argmax_spec(3, "cost_usd", "min")),
        context_text(["A", "B", "C"], sources=sources(3)),
        registry=BUILTIN_OPERATORS,
        accounting=costs(0.004, 0.001, 0.002),
    )

    evidence = outcome.evidence
    assert evidence.signal == SignalRecord(key="cost_usd", order="min")
    assert [set(m.signals) for m in evidence.members] == [{"cost_usd"}] * 3
    assert [m.signals["cost_usd"] for m in evidence.members] == [0.004, 0.001, 0.002]
    assert evidence.dropped == 0


@pytest.mark.parametrize(
    "args",
    [
        {"key": "logprob_mean", "order": "max"},
        {"key": "cost_usd"},
        {"key": "cost_usd", "order": "max", "x": 1},
        {"order": "max"},
        {"key": "cost_usd", "order": "middle"},
        {"key": 1, "order": "max"},
    ],
)
def test_by_signal_rejects_bad_args_without_echoing_the_key(args: dict[str, Any]) -> None:
    spec = argmax_spec(3, "cost_usd", "max")
    spec["reduce"] = {"op": "by_signal@1", "args": args}

    failure = _failure(spec, ["A", "B", "C"], sources=sources(3))

    assert failure.code == "combine_spec_invalid"
    assert "by_signal@1 args are invalid" in str(failure)
    assert "logprob_mean" not in str(failure)


@pytest.mark.parametrize(
    "args", [{}, {"order": "middle"}, {"order": None}, {"order": "max", "x": 1}]
)
def test_best_holder_rejects_bad_args(args: dict[str, Any]) -> None:
    spec = argmax_spec(3, "field:s", "max")
    spec["select"] = {"op": "best_holder@1", "args": args}

    failure = _failure(spec, _field_texts([1, 2, 3]))

    assert failure.code == "combine_spec_invalid"
    assert "best_holder@1 args are invalid" in str(failure)


def test_an_accounting_key_without_sources_is_a_spec_error() -> None:
    failure = _failure(argmax_spec(3, "cost_usd", "min"), ["A", "B", "C"])

    assert failure.code == "combine_spec_invalid"
