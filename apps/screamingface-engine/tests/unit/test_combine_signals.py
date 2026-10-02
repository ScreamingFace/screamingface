"""The signal a combine spec reads, resolved by the core (OME-1289 E4a gap-closure, unit 1).

FEATURE: the core reads the ONE signal a spec names -- a ``field:`` number from the member text, or
an accounting number through an injected reader -- and writes it on each member's ``Answer`` before
reduce. SG#11, SG#12, SG#14, SG#17 and the grammar of ``weights: {"signal": key}``.
Every test uses the fake operators of ``combine_support``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from combine_support import (
    FAKE_REGISTRY,
    context_text,
    run,
    spec_text,
    vote_spec,
)

from screamingface_engine.combine.evidence import SignalRecord
from screamingface_engine.combine.ports import (
    CombineError,
    CombineInput,
    MemberSources,
    OpArgs,
    OperatorDescriptor,
    Reduction,
    SignalRead,
    field_signal_value,
)
from screamingface_engine.combine.registry import OperatorRegistry

_MIB = 1024 * 1024
_FIELD_C = {"signal": "field:c"}


def _field_spec(count: int, **overrides: Any) -> dict[str, Any]:
    return vote_spec(count, weights=_FIELD_C, **overrides)


# --- SG#12: a field number, a bool, or None ---------------------------------------------------


@pytest.mark.parametrize(
    ("reply", "number"),
    [
        ('{"c": 0.8}', 0.8),
        ('{"c": true}', 1.0),
        ('{"c": false}', 0.0),
        ('{"c": 3}', 3.0),
        ('{"c": "0.8"}', None),
        ('{"c": 1e999}', None),
        ('{"c": 1e308}', 1e308),
        ('{"d": 1}', None),
        ("no json", None),
        ('see:\n```json\n{"c": 0.5}\n```', 0.5),
        ('{"c": 1}' + " " * _MIB, None),
        ('{"c": -2}', -2.0),
    ],
    ids=[
        "float", "true", "false", "int", "numeric-string", "overflow-float", "huge-finite",
        "missing", "not-json", "fenced", "too-large", "negative",
    ],
)  # fmt: skip
def test_field_signal_reads_number_or_bool(reply: str, number: float | None) -> None:
    outcome = run(spec_text(_field_spec(1)), context_text([reply]))
    row = outcome.evidence.members[0]
    assert row.signals == {"field:c": number}
    assert outcome.evidence.signal == SignalRecord(key="field:c", order=None)
    # The core sets the vote weight from the signal; zero, negative and None do not vote.
    if number is not None and 0 < number <= 7e305:
        assert row.weight == number
    else:
        assert row.weight is None


def test_a_field_weight_drives_a_weight_aware_reducer() -> None:
    texts = ['{"c": 2, "v": "a"}', '{"c": 1.5, "v": "b"}', '{"c": 1, "v": "b"}']
    spec = _field_spec(3, reduce={"op": "fake_weighted@1", "args": {}})
    evidence = run(spec_text(spec), context_text(texts)).evidence
    assert [row.weight for row in evidence.members] == [2.0, 1.5, 1.0]
    assert evidence.tally is not None
    assert [(row.value, row.score) for row in evidence.tally] == [('"b"}', 2.5), ('"a"}', 2.0)]
    assert evidence.chosen == ["member_2"]
    assert [row.signals for row in evidence.members] == [{"field:c": v} for v in (2.0, 1.5, 1.0)]


def test_a_member_that_failed_extract_still_carries_its_signal() -> None:
    spec = _field_spec(2, extract={"op": "fake_digits@1", "args": {}})
    rows = run(spec_text(spec), context_text(['{"c": true}', '{"c": 4}'])).evidence.members
    assert [(row.status, row.reason, row.signals["field:c"]) for row in rows] == [
        ("fail", "empty", 1.0),
        ("answered", None, 4.0),
    ]


# --- SG#14: only the signal the spec reads is written -----------------------------------------


def _score_spec(count: int, key: str, order: str = "max", **overrides: Any) -> dict[str, Any]:
    return vote_spec(
        count,
        reduce={"op": "fake_signal_score@1", "args": {"key": key, "order": order}},
        select={"op": "fake_best@1", "args": {}},
        **overrides,
    )


def test_only_read_signals_are_written() -> None:
    plain = run(spec_text(vote_spec(2)), context_text(["a x", "b y"])).evidence
    assert [row.signals for row in plain.members] == [{}, {}]
    assert plain.signal is None
    texts = ['{"x": 1, "v": "a"}', '{"x": 5, "v": "b"}', '{"x": 3, "v": "c"}']
    scored = run(spec_text(_score_spec(3, "field:x")), context_text(texts)).evidence
    assert [set(row.signals) for row in scored.members] == [{"field:x"}] * 3
    assert scored.signal == SignalRecord(key="field:x", order="max")
    assert scored.chosen == ["member_2"]
    assert [row.score for row in scored.members] == [1.0, 5.0, 3.0]


def test_a_step_reads_at_most_one_signal() -> None:
    spec = _score_spec(2, "cost_usd", weights={"signal": "field:c"})
    with pytest.raises(CombineError) as caught:
        run(spec_text(spec), context_text(["a", "b"]))
    assert caught.value.code == "combine_spec_invalid"
    assert "at most one signal" in str(caught.value)


def _registry_with_read(read: Any) -> OperatorRegistry:
    def reduce(combine_input: CombineInput, args: OpArgs, /) -> Reduction:
        return Reduction()

    return OperatorRegistry(
        (
            *FAKE_REGISTRY,
            OperatorDescriptor("fake_reads", 1, "reduce", "t.", reduce, signal_read=read),
        )
    )


def test_a_plugin_that_reads_an_unknown_signal_is_spec_invalid() -> None:
    registry = _registry_with_read(lambda args: SignalRead("score:judge", "max"))
    spec = vote_spec(2, reduce={"op": "fake_reads@1", "args": {}})
    with pytest.raises(CombineError) as caught:
        run(spec_text(spec), context_text(["a", "b"]), registry=registry)
    assert caught.value.code == "combine_spec_invalid"
    assert "fake_reads@1 reads an unknown signal" in str(caught.value)
    assert "score:judge" not in str(caught.value)


def test_a_plugin_that_reads_with_a_bad_order_is_a_plugin_bug() -> None:
    registry = _registry_with_read(lambda args: SignalRead("cost_usd", "middle"))  # type: ignore[arg-type]
    spec = vote_spec(2, reduce={"op": "fake_reads@1", "args": {}})
    with pytest.raises(RuntimeError, match="fake_reads@1") as caught:
        run(spec_text(spec), context_text(["a", "b"]), registry=registry)
    assert not isinstance(caught.value, CombineError)


def test_a_plugin_that_reads_nothing_leaves_signals_empty() -> None:
    registry = _registry_with_read(lambda args: None)
    spec = vote_spec(
        2,
        reduce={"op": "fake_reads@1", "args": {}},
        select={"op": "fake_constant@1", "args": {}},
    )
    evidence = run(spec_text(spec), context_text(["a", "b"]), registry=registry).evidence
    assert evidence.signal is None
    assert [row.signals for row in evidence.members] == [{}, {}]


# --- SG#11: accounting numbers through the injected reader ------------------------------------


def _sources(count: int) -> dict[str, Any]:
    call = {"path": "/provider/alpha", "params": ""}
    return {f"member_{i}": {"model_1": dict(call)} for i in range(1, count + 1)}


def _cost_context(count: int = 3) -> str:
    return context_text([f"{chr(96 + i)} x" for i in range(1, count + 1)], sources=_sources(count))


def test_missing_cost_is_none_not_error() -> None:
    seen: list[MemberSources] = []

    def reader(sources: MemberSources, /) -> Mapping[str, Mapping[str, float | None]]:
        seen.append(sources)
        return {
            "member_1": {"cost_usd": 0.004},
            "member_2": {"cost_usd": None},
            "member_3": {"cost_usd": float("nan")},
        }

    outcome = run(spec_text(_score_spec(3, "cost_usd", "min")), _cost_context(), accounting=reader)
    assert [row.signals for row in outcome.evidence.members] == [
        {"cost_usd": 0.004},
        {"cost_usd": None},
        {"cost_usd": None},
    ]
    assert outcome.evidence.signal == SignalRecord(key="cost_usd", order="min")
    assert len(seen) == 1
    assert seen[0]["member_1"]["model_1"] == ("/provider/alpha", ())


def test_no_reader_gives_none_for_every_member() -> None:
    outcome = run(spec_text(_score_spec(3, "cost_usd")), _cost_context(), accounting=None)
    assert [row.signals for row in outcome.evidence.members] == [{"cost_usd": None}] * 3
    assert outcome.evidence.result.status == "abstain"  # fake_best finds no scored member


def test_the_reader_values_are_clean_floats_or_none() -> None:
    def reader(sources: MemberSources, /) -> Mapping[str, Mapping[str, float | None]]:
        return {
            "member_1": {"cost_usd": True},  # type: ignore[dict-item]
            "member_2": {"cost_usd": float("inf")},
            "member_3": {"cost_usd": "1.5"},  # type: ignore[dict-item]
            "stranger": {"cost_usd": 9.0},
        }

    outcome = run(spec_text(_score_spec(3, "cost_usd")), _cost_context(), accounting=reader)
    assert [row.signals for row in outcome.evidence.members] == [{"cost_usd": None}] * 3


def test_an_integer_from_the_reader_becomes_a_float() -> None:
    def reader(sources: MemberSources, /) -> Mapping[str, Mapping[str, float | None]]:
        return {"member_1": {"cost_usd": 2}, "member_2": {"cost_usd": 1}, "member_3": {}}

    outcome = run(spec_text(_score_spec(3, "cost_usd")), _cost_context(), accounting=reader)
    assert [row.signals["cost_usd"] for row in outcome.evidence.members] == [2.0, 1.0, None]
    assert all(
        isinstance(row.signals["cost_usd"], (float, type(None))) for row in outcome.evidence.members
    )
    assert outcome.evidence.chosen == ["member_1"]


@pytest.mark.parametrize("key", ["latency_ms", "tokens_in", "tokens_out"])
def test_every_accounting_key_is_read_from_its_own_slot(key: str) -> None:
    def reader(sources: MemberSources, /) -> Mapping[str, Mapping[str, float | None]]:
        return {
            member: {"cost_usd": 1.0, "latency_ms": 2.0, "tokens_in": 3.0, "tokens_out": 4.0}
            for member in sources
        }

    expected = {"latency_ms": 2.0, "tokens_in": 3.0, "tokens_out": 4.0}[key]
    outcome = run(spec_text(_score_spec(3, key)), _cost_context(), accounting=reader)
    assert [row.signals for row in outcome.evidence.members] == [{key: expected}] * 3


def test_sources_must_match_the_signal_kind() -> None:
    # An accounting key needs sources; a field key (or no signal) must not carry them.
    with pytest.raises(CombineError) as absent:
        run(spec_text(_score_spec(2, "cost_usd")), context_text(["a", "b"]))
    assert absent.value.code == "combine_spec_invalid"
    with pytest.raises(CombineError) as present:
        run(spec_text(_score_spec(2, "field:c")), context_text(["a", "b"], sources=_sources(2)))
    assert present.value.code == "combine_spec_invalid"
    with pytest.raises(CombineError) as unread:
        run(spec_text(vote_spec(2)), context_text(["a", "b"], sources=_sources(2)))
    assert unread.value.code == "combine_spec_invalid"


def test_malformed_sources_fails_before_any_operator_runs() -> None:
    def extract(text: str, args: OpArgs, /) -> Any:
        raise AssertionError("no operator may run before the context is valid")

    registry = OperatorRegistry(
        (*FAKE_REGISTRY, OperatorDescriptor("fake_tripwire", 1, "extract", "t.", extract))
    )
    spec = _score_spec(2, "cost_usd", extract={"op": "fake_tripwire@1", "args": {}})
    bad = {"member_1": {"model_1": {"path": "/p", "params": "b=1&a=2"}}, "member_2": {}}
    with pytest.raises(CombineError) as caught:
        run(spec_text(spec), context_text(["a", "b"], sources=bad), registry=registry)
    assert caught.value.code == "combine_spec_invalid"


# --- SG#17: the depth cap holds for field signals ---------------------------------------------


def _nested(depth: int) -> str:
    return "[" * depth + "]" * depth


def test_field_path_keeps_depth_cap() -> None:
    fits = '{"a": 1, "b": ' + _nested(63) + "}"
    too_deep = '{"a": 1, "b": ' + _nested(64) + "}"
    assert field_signal_value(fits, "a") == 1.0
    assert field_signal_value(too_deep, "a") is None
    assert field_signal_value("[" * 100000, "a") is None
    for reply in (fits, too_deep, "[" * 100000):
        outcome = run(spec_text(_field_spec(1)), context_text([reply]))
        assert outcome.evidence.members[0].signals["field:c"] is None
