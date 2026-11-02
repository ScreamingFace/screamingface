"""The strict combine-spec and context parsers (FW-2, FW-E3; OME-1289 E4a, unit 1)."""

from __future__ import annotations

import copy
import json
import sys
from collections.abc import Callable
from typing import Any

import pytest
from combine_support import context_text, vote_spec

from screamingface_engine.combine import endpoint
from screamingface_engine.combine.ports import SpecInvalid
from screamingface_engine.combine.spec import (
    MAX_MEMBERS,
    MAX_WEIGHT,
    CombineSpec,
    SignalWeights,
    canonical_params,
    parse_context,
    parse_spec,
)


def _dump(spec: dict[str, Any]) -> str:
    return json.dumps(spec)


def _without(spec: dict[str, Any], key: str) -> dict[str, Any]:
    trimmed = copy.deepcopy(spec)
    del trimmed[key]
    return trimmed


def _deep(depth: int) -> Any:
    value: Any = 1
    for _ in range(depth):
        value = [value]
    return value


def test_a_valid_vote_spec_parses() -> None:
    spec = parse_spec(_dump(vote_spec(3)))
    assert isinstance(spec, CombineSpec)
    assert spec.reducer == "vote"
    assert spec.members == ["member_1", "member_2", "member_3"]
    assert spec.extract is not None and spec.extract.op == "fake_last_word@1"
    assert spec.reduce.op == "fake_count@1"
    assert spec.weights is None


_BAD_SPECS: dict[str, Callable[[], str]] = {
    "not-json": lambda: "not json",
    "a-list": lambda: "[]",
    "wrong-schema": lambda: _dump(vote_spec(schema="screamingface.combine-spec.v2")),
    "missing-schema": lambda: _dump(_without(vote_spec(), "schema")),
    "unknown-top-key": lambda: _dump(vote_spec(surprise=1)),
    "unknown-step-key": lambda: _dump(
        vote_spec(reduce={"op": "fake_count@1", "args": {}, "extra": 1})
    ),
    "missing-weights-key": lambda: _dump(_without(vote_spec(), "weights")),
    "op-without-at": lambda: _dump(vote_spec(reduce={"op": "fake_count", "args": {}})),
    "duplicate-json-key": lambda: '{"schema":"a","schema":"b"}',
    "duplicate-members": lambda: _dump(vote_spec(members=["member_1", "member_1"])),
    "member-zero": lambda: _dump(vote_spec(members=["member_0"])),
    "empty-members": lambda: _dump(vote_spec(members=[])),
    "depth-65-args": lambda: _dump(
        vote_spec(extract={"op": "fake_last_word@1", "args": {"deep": _deep(64)}})
    ),
    "nan-token": lambda: _dump(vote_spec()).replace('"weights": null', '"weights": NaN'),
}


@pytest.mark.parametrize("make", _BAD_SPECS.values(), ids=list(_BAD_SPECS))
def test_spec_parse_rejects_unknown_keys_wrong_schema_and_member_mismatch(
    make: Callable[[], str],
) -> None:
    with pytest.raises(SpecInvalid):
        parse_spec(make())


_BAD_CONTEXTS: dict[str, str] = {
    "extra-output": context_text(["a", "b", "c", "d"]),
    "missing-output": context_text(["a", "b"]),
    "non-str-output": json.dumps(
        {"input": "q", "outputs": {"member_1": 1, "member_2": "b", "member_3": "c"}}
    ),
    "bad-signal-name": context_text(["a", "b", "c"], {"oracle": "x"}),
    "extra-top-key": json.dumps(
        {"input": "q", "outputs": {"member_1": "a", "member_2": "b", "member_3": "c"}, "extra": 1}
    ),
    "not-json": "not json",
    "not-an-object": "[]",
    "missing-input": json.dumps({"outputs": {"member_1": "a", "member_2": "b", "member_3": "c"}}),
    "non-str-input": json.dumps(
        {"input": 1, "outputs": {"member_1": "a", "member_2": "b", "member_3": "c"}}
    ),
}


@pytest.mark.parametrize("context", _BAD_CONTEXTS.values(), ids=list(_BAD_CONTEXTS))
def test_context_parse_rejects_a_bad_shape(context: str) -> None:
    with pytest.raises(SpecInvalid):
        parse_context(context, ["member_1", "member_2", "member_3"])


def test_context_parse_keeps_outputs_and_signals() -> None:
    parsed = parse_context(
        context_text(["a", "b"], {"judge": "member_1", "writer_title": "member_2"}),
        ["member_1", "member_2"],
    )
    assert parsed.input == "q"
    assert dict(parsed.outputs) == {"member_1": "a", "member_2": "b"}
    assert dict(parsed.signals) == {"judge": "member_1", "writer_title": "member_2"}
    assert dict(parse_context(context_text(["a"]), ["member_1"]).signals) == {}


def test_spec_rejects_bad_weights() -> None:
    members = ["member_1", "member_2"]
    bad = [
        {"member_1": 1.0},
        {"member_1": 1.0, "member_2": 2.0, "member_3": 1.0},
        {"member_1": 1.0, "member_9": 2.0},
        {"member_1": 0, "member_2": 1.0},
        {"member_1": -1, "member_2": 1.0},
        {"member_1": 1.0, "member_2": True},
    ]
    for weights in bad:
        with pytest.raises(SpecInvalid):
            parse_spec(_dump(vote_spec(2, members=members, weights=weights)))
    with pytest.raises(SpecInvalid):
        parse_spec(
            _dump(vote_spec(2)).replace(
                '"weights": null', '"weights": {"member_1": 1e309, "member_2": 1}'
            )
        )
    accepted = parse_spec(_dump(vote_spec(2, weights={"member_1": 2, "member_2": 1.5})))
    assert accepted.weights == {"member_1": 2.0, "member_2": 1.5}


def _median(normalize_op: str) -> dict[str, Any]:
    return vote_spec(reducer="median", normalize={"op": normalize_op, "args": {}})


_BAD_STAGE_SPECS: dict[str, dict[str, Any]] = {
    "judge-with-extract": vote_spec(reducer="judge"),
    "vote-without-extract": vote_spec(extract=None),
    "median-without-normalize": vote_spec(reducer="median", normalize=None),
    "normalize-without-extract": vote_spec(reducer="project", extract=None),
    "concat-with-extract": vote_spec(reducer="concat"),
    "median-with-identity-normalize": _median("identity@1"),
    "median-with-a-name-that-only-starts-with-numeric": _median("numeric_plus@1"),
}


@pytest.mark.parametrize("spec", _BAD_STAGE_SPECS.values(), ids=list(_BAD_STAGE_SPECS))
def test_reducer_stage_rules(spec: dict[str, Any]) -> None:
    with pytest.raises(SpecInvalid):
        parse_spec(_dump(spec))


@pytest.mark.parametrize(
    "spec",
    [
        vote_spec(reducer="judge", extract=None, normalize=None),
        vote_spec(reducer="concat", extract=None, normalize=None),
        _median("numeric@1"),
        _median("numeric@2"),
        vote_spec(reducer="project", normalize=None),
    ],
    ids=["judge", "concat", "median-numeric-1", "median-numeric-2", "project"],
)
def test_reducer_stage_rules_accept_the_legal_counterparts(spec: dict[str, Any]) -> None:
    assert parse_spec(_dump(spec)).reducer == spec["reducer"]


def test_spec_errors_name_locations_not_values() -> None:
    broken = vote_spec(
        surprise=1,
        extract={"op": "SECRET-ARG", "args": {"key": "SECRET-ARG"}},
        members=["SECRET-ARG"],
    )
    with pytest.raises(SpecInvalid) as caught:
        parse_spec(_dump(broken))
    message = str(caught.value)
    assert "SECRET-ARG" not in message
    assert "extract.op" in message or "surprise" in message


# --- weights: a cap that keeps every sum finite, and only the vote reducer takes them ---------


def test_the_weight_cap_keeps_a_sum_over_every_member_finite() -> None:
    assert MAX_MEMBERS == 256
    assert endpoint.MAX_MEMBERS is MAX_MEMBERS
    assert sys.float_info.max / MAX_MEMBERS == MAX_WEIGHT
    assert MAX_WEIGHT * MAX_MEMBERS <= sys.float_info.max


def test_a_weight_above_the_cap_is_invalid_and_the_cap_itself_is_accepted() -> None:
    with pytest.raises(SpecInvalid):
        parse_spec(_dump(vote_spec(2, weights={"member_1": 1e308, "member_2": 1e308})))
    at_cap = parse_spec(_dump(vote_spec(2, weights={"member_1": MAX_WEIGHT, "member_2": 1})))
    assert at_cap.weights == {"member_1": MAX_WEIGHT, "member_2": 1.0}


_LEGAL_STAGES: dict[str, dict[str, Any]] = {
    "vote": {},
    "median": {"normalize": {"op": "numeric@1", "args": {}}},
    "judge": {"extract": None, "normalize": None},
    "pick": {},
    "merge": {"extract": None, "normalize": None},
    "project": {"normalize": None},
    "rank": {"extract": None, "normalize": None},
    "concat": {"extract": None, "normalize": None},
}


@pytest.mark.parametrize(
    "reducer", [name for name in _LEGAL_STAGES if name not in ("vote", "median")]
)
def test_only_the_vote_reducer_takes_weights(reducer: str) -> None:
    legal = vote_spec(2, reducer=reducer, **_LEGAL_STAGES[reducer])
    assert parse_spec(_dump(legal)).reducer == reducer  # the spec is legal without weights
    weighted = {**legal, "weights": {"member_1": 1.0, "member_2": 2.0}}
    with pytest.raises(SpecInvalid, match="weights"):
        parse_spec(_dump(weighted))


# --- the context: unique keys; the error text is short ---------------------------------------


def test_a_duplicate_member_key_in_the_context_is_invalid() -> None:
    context = '{"input":"q","outputs":{"member_1":"a","member_1":"b"}}'
    with pytest.raises(SpecInvalid):
        parse_context(context, ["member_1"])


def test_a_long_location_in_an_error_is_cut_to_64_characters() -> None:
    with pytest.raises(SpecInvalid) as caught:
        parse_spec(_dump(vote_spec(**{"k" * 200: 1})))
    message = str(caught.value)
    assert "k" * 64 + "\u2026" in message
    assert "k" * 65 not in message


# --- the signal weights grammar and the context sources (gap-closure unit 1) ------------------

_CALL = {"path": "/provider/alpha", "params": "temperature=0.0"}


def _sources(**overrides: Any) -> dict[str, Any]:
    sources: dict[str, Any] = {"member_1": {"model_1": dict(_CALL)}, "member_2": {}}
    sources.update(overrides)
    return sources


def _parse_sources(sources: Any, *, expected: bool = True) -> Any:
    return parse_context(
        context_text(["a", "b"], sources=sources),
        ["member_1", "member_2"],
        sources_expected=expected,
    )


def test_well_formed_sources_parse_to_read_only_fingerprints() -> None:
    context = _parse_sources(_sources(member_2={"c_2": {"path": "/provider/beta", "params": ""}}))
    assert context.sources is not None
    assert dict(context.sources["member_1"]) == {
        "model_1": ("/provider/alpha", (("temperature", "0.0"),))
    }
    assert dict(context.sources["member_2"]) == {"c_2": ("/provider/beta", ())}
    with pytest.raises(TypeError):
        context.sources["member_1"]["x"] = ("/p", ())  # type: ignore[index]
    assert _parse_sources({"member_1": {}, "member_2": {}}).sources is not None
    assert parse_context(context_text(["a", "b"]), ["member_1", "member_2"]).sources is None


_BAD_SOURCES: dict[str, Any] = {
    "keys-differ-from-outputs": {"member_1": {}},
    "member-not-a-dict": _sources(member_1=[]),
    "entry-missing-path": _sources(member_1={"c": {"params": ""}}),
    "entry-extra-key": _sources(member_1={"c": {**_CALL, "extra": 1}}),
    "path-empty": _sources(member_1={"c": {"path": "", "params": ""}}),
    "params-not-a-str": _sources(member_1={"c": {"path": "/p", "params": 1}}),
    "call-key-bad": _sources(member_1={"a-b": dict(_CALL)}),
    "params-unsorted": _sources(member_1={"c": {"path": "/p", "params": "b=1&a=2"}}),
    "params-over-encoded": _sources(member_1={"c": {"path": "/p", "params": "%41=1"}}),
    "params-duplicate-key": _sources(member_1={"c": {"path": "/p", "params": "a=1&a=2"}}),
    "params-bad-utf8": _sources(member_1={"c": {"path": "/p", "params": "%ff=1"}}),
    "sources-a-list": [],
}


@pytest.mark.parametrize("sources", _BAD_SOURCES.values(), ids=list(_BAD_SOURCES))
def test_malformed_sources_is_spec_invalid(sources: Any) -> None:
    with pytest.raises(SpecInvalid):
        _parse_sources(sources)


def test_sources_are_present_exactly_when_the_spec_reads_an_accounting_signal() -> None:
    with pytest.raises(SpecInvalid) as present:
        _parse_sources(_sources(), expected=False)
    with pytest.raises(SpecInvalid) as absent:
        parse_context(context_text(["a", "b"]), ["member_1", "member_2"], sources_expected=True)
    for caught in (present, absent):
        assert "sources" in str(caught.value)
        assert "/provider/alpha" not in str(caught.value)


def test_a_sources_error_never_echoes_a_path_or_params() -> None:
    bad = _sources(member_1={"c": {"path": "/SECRET-PATH", "params": "z=SECRET&a=1"}})
    with pytest.raises(SpecInvalid) as caught:
        _parse_sources(bad)
    assert "SECRET" not in str(caught.value)


def test_canonical_params_round_trip() -> None:
    text = canonical_params((("x.y", "1"), ("a", "b c")))
    assert text == "a=b%20c&x.y=1"
    context = _parse_sources(_sources(member_1={"c": {"path": "/p", "params": text}}))
    assert context.sources is not None
    assert context.sources["member_1"]["c"] == ("/p", (("a", "b c"), ("x.y", "1")))
    assert canonical_params(()) == ""
    assert canonical_params((("k", "a&b=c%"),)) == "k=a%26b%3Dc%25"
    empty = _parse_sources(_sources(member_1={"c": {"path": "/p", "params": ""}}))
    assert empty.sources is not None and empty.sources["member_1"]["c"] == ("/p", ())


def test_weights_accept_a_signal_ref_and_reject_unknown_keys() -> None:
    for key in ("field:confidence", "cost_usd", "field:a.b[0]", "tokens_out", "score:judge"):
        parsed = parse_spec(_dump(vote_spec(2, weights={"signal": key})))
        assert parsed.weights == SignalWeights(signal=key)
    bad_weights = [
        {"signal": "logprob_mean"},
        {"signal": "field:a..b"},
        {"signal": "cost_usd", "member_1": 1},
        {"signal": 1},
        {"signal": "cost_usd", "extra": "x"},
    ]
    for weights in bad_weights:
        with pytest.raises(SpecInvalid) as caught:
            parse_spec(_dump(vote_spec(2, weights=weights)))
        for leaked in ("logprob_mean", "a..b"):
            assert leaked not in str(caught.value)
    pick = vote_spec(
        3,
        reducer="pick",
        normalize={"op": "numeric@1", "args": {}},
        weights={"signal": "cost_usd"},
    )
    with pytest.raises(SpecInvalid, match="weights"):
        parse_spec(_dump(pick))
