"""The strict combine-spec and context parsers (FW-2, FW-E3; OME-1289 E4a, unit 1)."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from typing import Any

import pytest
from combine_support import context_text, vote_spec

from screamingface_engine.combine.ports import SpecInvalid
from screamingface_engine.combine.spec import CombineSpec, parse_context, parse_spec


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
        context_text(["a", "b"], {"judge": "member_1", "writer.title": "member_2"}),
        ["member_1", "member_2"],
    )
    assert parsed.input == "q"
    assert dict(parsed.outputs) == {"member_1": "a", "member_2": "b"}
    assert dict(parsed.signals) == {"judge": "member_1", "writer.title": "member_2"}
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
    "median-with-text-normalize": _median("text@1"),
    "median-with-a-name-that-only-starts-with-numeric": _median("numeric_plus@1"),
}


@pytest.mark.parametrize("spec", _BAD_STAGE_SPECS.values(), ids=list(_BAD_STAGE_SPECS))
def test_reducer_stage_rules(spec: dict[str, Any]) -> None:
    with pytest.raises(SpecInvalid):
        parse_spec(_dump(spec))


def test_a_median_spec_needs_a_numeric_normalize_step_and_names_no_values() -> None:
    with pytest.raises(SpecInvalid) as caught:
        parse_spec(_dump(_median("identity@1")))
    assert "numeric" in str(caught.value)
    assert "identity" not in str(caught.value)


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
