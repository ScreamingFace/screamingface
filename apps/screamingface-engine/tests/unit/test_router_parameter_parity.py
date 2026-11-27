"""The Engine reads Model parameter schemas as the Gateway publishes and the SDK decodes them.

FEATURE: Router Recipe extension (contract C4; Unit 5.2). A parameter row the Gateway could never
publish, or a value either reader refuses, is a preflight mismatch here, never a paid call.

INVARIANT: a parameter schema's `pattern` and `maxLength` stand only on a top-level type list
that holds `string`, and a pattern is a string anchored with `^` and `$` that compiles: the
Gateway's `ParameterSchema` rule, which the SDK's discovery reader applies alike.
INVARIANT: a parameter schema reads only inside the vocabulary that both the Gateway publishes and
the SDK decodes: the keys the Gateway renders, and an item schema of `type` alone; distinct type
names; bounds a float holds, compared as that float, `minimum <= maximum`; an enum of distinct
non-blank strings with no surrounding blanks; an item type other than `array`; a pattern the
regex compiler reads. An empty enum reads, and no value fits it.
WHY data and no import of the Gateway or the SDK: the Engine depends on neither, so these vectors
restate the contract here.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from router_block_support import block, run_block
from router_support import admit_step, fixed_definition, posts, refusal, router_gateway, spec_text
from routing_support import PARAMETERS_PATH, max_tokens_rule, parameters_document

from screamingface_engine.world.parameter_contract import _constraints_readable, value_fits
from screamingface_engine.world.request_parameters import model_params

# --- Model parameter schemas (C4) -------------------------------------------------------------

_NOT_STRING = [
    pytest.param("integer", 3, id="integer"),
    pytest.param("number", 0.5, id="number"),
    pytest.param("boolean", True, id="boolean"),
    pytest.param("array", [], id="array"),
    pytest.param("object", {}, id="object"),
]


@pytest.mark.parametrize(
    "constraint",
    [
        pytest.param({"pattern": "^x$"}, id="pattern"),
        pytest.param({"maxLength": 3}, id="maxLength"),
    ],
)
@pytest.mark.parametrize(("kind", "value"), _NOT_STRING)
def test_a_text_constraint_on_a_type_that_is_not_string_capable_misfits(
    kind: str, value: object, constraint: dict[str, object]
) -> None:
    # WHY: the Gateway refuses to publish this row; a constraint that can never fire would read
    # as protection that is absent.
    assert value_fits(max_tokens_rule(schema={"type": kind}), value) is True
    assert value_fits(max_tokens_rule(schema={"type": kind, **constraint}), value) is False


@pytest.mark.parametrize(
    ("schema", "value"),
    [
        pytest.param({"type": ["integer", "array"], "pattern": "^x$"}, 3, id="list-without-string"),
        pytest.param(
            {"type": "array", "items": {"type": "string"}, "maxLength": 3},
            ["x"],
            id="string-items-are-not-a-string-type",
        ),
        pytest.param({"type": "string", "pattern": "x"}, "x", id="unanchored"),
        pytest.param({"type": "string", "pattern": "^x"}, "x", id="no-end-anchor"),
        pytest.param({"type": "string", "pattern": "x$"}, "x", id="no-start-anchor"),
        pytest.param({"type": ["string", "array"], "pattern": "x"}, "x", id="unanchored-in-a-list"),
        pytest.param({"type": "string", "pattern": 5}, "x", id="pattern-a-number"),
        pytest.param({"type": "string", "pattern": ["^x$"]}, "x", id="pattern-a-list"),
        pytest.param({"type": "string", "pattern": "^[$"}, "x", id="anchored-but-broken"),
        pytest.param({"type": "string", "maxLength": True}, "x", id="maxLength-a-boolean"),
        pytest.param({"type": "string", "maxLength": 0}, "", id="maxLength-zero"),
    ],
)
def test_a_text_constraint_the_gateway_could_not_publish_misfits(
    schema: dict[str, object], value: object
) -> None:
    assert value_fits(max_tokens_rule(schema=schema), value) is False


@pytest.mark.parametrize(
    ("schema", "value", "fits"),
    [
        pytest.param({"type": "string", "pattern": "^x$"}, "x", True, id="anchored-match"),
        pytest.param({"type": "string", "pattern": "^x$"}, "y", False, id="anchored-miss"),
        pytest.param({"type": "string", "maxLength": 3}, "abc", True, id="at-max-length"),
        pytest.param({"type": "string", "maxLength": 3}, "abcd", False, id="past-max-length"),
        pytest.param(
            {"type": ["string", "array"], "pattern": "^x$", "maxLength": 1}, "x", True, id="mixed"
        ),
        pytest.param(
            {"type": ["string", "array"], "pattern": "^x$", "maxLength": 1},
            ["a", "b"],
            True,
            id="mixed-array-value",
        ),
        pytest.param({"type": ["array", "string"], "pattern": "^x$"}, "xx", False, id="mixed-miss"),
        pytest.param(
            {"type": "integer", "pattern": None, "maxLength": None}, 3, True, id="null-is-absent"
        ),
    ],
)
def test_a_string_capable_schema_keeps_its_text_constraints(
    schema: dict[str, object], value: object, fits: bool
) -> None:
    assert value_fits(max_tokens_rule(schema=schema), value) is fits


def _scripted(name: str, sent: str, schema: dict[str, object]) -> tuple[dict[str, Any], Any]:
    """A fixed Router whose first candidate also sends ``name=sent``, published under ``schema``."""
    definition = fixed_definition()
    target = definition["candidates"][0]["model"]
    target["params"][name] = sent
    document = parameters_document(target["model"])
    document["parameters"][name] = max_tokens_rule(request_path=name, schema=schema)
    gateway = router_gateway()
    gateway.script[(PARAMETERS_PATH, target["model"])] = lambda _request: document
    return definition, gateway


def _admitted(name: str, sent: str, schema: dict[str, object]) -> tuple[dict[str, Any], Any]:
    """ADMIT that Router's occurrence."""
    definition, gateway = _scripted(name, sent, schema)
    return json.loads(admit_step(gateway, spec_text(definition))), gateway


@pytest.mark.parametrize(
    ("name", "sent", "schema"),
    [
        pytest.param(
            "reasoning_effort", "high", {"type": "string", "pattern": "high"}, id="unanchored"
        ),
        pytest.param(
            "reasoning_effort", "high", {"type": "string", "pattern": 7}, id="pattern-a-number"
        ),
        pytest.param("seed", "7", {"type": "integer", "pattern": "^7$"}, id="pattern-on-integer"),
        pytest.param("stop", '["x"]', {"type": "array", "maxLength": 2}, id="maxLength-on-array"),
        pytest.param(
            "metadata", '{"a": "b"}', {"type": "object", "pattern": "^x$"}, id="on-object"
        ),
    ],
)
def test_admit_refuses_a_parameter_row_the_gateway_could_not_publish_before_any_post(
    name: str, sent: str, schema: dict[str, object]
) -> None:
    document, gateway = _admitted(name, sent, schema)

    # INVARIANT (C4): a malformed row is a preflight mismatch, never a paid call.
    assert document == refusal("routing_profile_mismatch")
    assert posts(gateway) == []


def test_admit_keeps_a_string_capable_parameter_row() -> None:
    schema = {"type": ["string", "integer"], "pattern": "^(low|high)$", "maxLength": 8}

    document, gateway = _admitted("reasoning_effort", "high", schema)

    assert set(document) == {"input", "spec"}
    assert posts(gateway) == []


# --- the vocabulary both readers share (C4) ---------------------------------------------------

_HUGE = 10**400
"""An integer JSON carries exactly and no float holds: neither a Gateway nor an SDK bound."""
_P53 = 2**53
_DEEP = "^" + "(?:" * 5000 + "a" + ")" * 5000 + "$"
"""Anchored and balanced, and nested past the regex compiler's recursion limit."""
_OUTSIDE = [
    pytest.param("seed", "1", {"type": "integer", "enum": [1, 2]}, id="enum-of-integers"),
    pytest.param("seed", "1", {"type": "integer", "enum": [True]}, id="enum-true-for-1"),
    pytest.param("logprobs", "true", {"type": "boolean", "enum": [1]}, id="enum-1-for-true"),
    pytest.param("stop", "a", {"type": "string", "enum": ["a", None]}, id="enum-null-member"),
    pytest.param("stop", "a", {"type": "string", "enum": ["a", ""]}, id="enum-empty-member"),
    pytest.param("stop", "a", {"type": "string", "enum": ["a", "  "]}, id="enum-blank-member"),
    pytest.param("stop", " a", {"type": "string", "enum": [" a"]}, id="enum-padded-member"),
    pytest.param("stop", "a", {"type": "string", "enum": ["a", "a"]}, id="enum-duplicate"),
    pytest.param(
        "stop", '[["a"]]', {"type": "array", "items": {"type": "array"}}, id="array-items"
    ),
    pytest.param("stop", "a", {"type": ["string", "string"]}, id="duplicate-type"),
    pytest.param(
        "stop", "a", {"type": ["string", "integer"], "minimum": 2, "maximum": 1}, id="inverted"
    ),
    pytest.param(
        "logprobs", "true", {"type": "boolean", "minimum": 1, "maximum": 0}, id="inverted-bool"
    ),
    pytest.param("seed", "1", {"type": "integer", "minimum": _HUGE}, id="huge-minimum"),
    pytest.param(
        "stop", "a", {"type": ["string", "integer"], "maximum": -_HUGE}, id="huge-maximum"
    ),
    pytest.param("seed", "999", {"type": "integer", "exclusiveMaximum": 1}, id="unknown-key"),
    pytest.param(
        "stop",
        '["ab"]',
        {"type": "array", "items": {"type": "string", "maxLength": 1}},
        id="item-key",
    ),
    pytest.param("stop", "a", {"type": "string", "pattern": "^a{4294967296}$"}, id="repeat-limit"),
]
_PUBLISHED = [
    pytest.param(
        "effort", "high", {"type": "string", "enum": ["low", "medium", "high"]}, id="enum"
    ),
    pytest.param("choice", '{"a": 1}', {"type": ["string", "object"]}, id="string-or-object"),
    pytest.param("stop", '["a"]', {"type": ["string", "array"], "items": {"type": "string"}}),
    pytest.param(
        "calls", "[{}]", {"type": "array", "items": {"type": "object"}}, id="object-items"
    ),
    pytest.param(
        "temperature", "2", {"type": "number", "minimum": 0.0, "maximum": 2.0}, id="number"
    ),
    pytest.param(
        "top", "5", {"type": "integer", "minimum": 5.0, "maximum": 5.0}, id="equal-bounds"
    ),
    pytest.param("seed", str(2**60), {"type": "integer", "minimum": 2**53 + 1}, id="large-bound"),
]


@pytest.mark.parametrize(("name", "sent", "schema"), _OUTSIDE)
def test_a_row_outside_the_shared_vocabulary_misfits_and_admit_refuses_it_before_any_post(
    name: str, sent: str, schema: dict[str, object]
) -> None:
    # INVARIANT (C4): a row either reader refuses is unreadable, and with string-only enum
    # members no `True == 1` alias lets a value of another type pass; nothing is paid for.
    assert value_fits(max_tokens_rule(schema=schema), model_params({name: sent})[name]) is False
    document, gateway = _admitted(name, sent, schema)
    assert document == refusal("routing_profile_mismatch")
    assert posts(gateway) == []


@pytest.mark.parametrize(("name", "sent", "schema"), _PUBLISHED)
def test_a_row_inside_the_shared_vocabulary_keeps_fitting_and_admit_accepts_it(
    name: str, sent: str, schema: dict[str, object]
) -> None:
    assert value_fits(max_tokens_rule(schema=schema), model_params({name: sent})[name]) is True
    document, gateway = _admitted(name, sent, schema)
    assert set(document) == {"input", "spec"}


@pytest.mark.parametrize(
    ("sent", "constraint", "fits"),
    [
        pytest.param(_P53 + 1, {"maximum": _P53 + 1}, False, id="above-a-maximum-held-as-2**53"),
        pytest.param(_P53, {"minimum": _P53 + 1}, True, id="meets-a-minimum-held-as-2**53"),
        pytest.param(_P53 + 4, {"maximum": _P53 + 3}, True, id="meets-a-maximum-held-as-2**53+4"),
        pytest.param(_P53, {"minimum": _P53 + 1, "maximum": _P53}, True, id="equal-as-floats"),
        pytest.param(1, {"enum": []}, False, id="empty-enum-admits-no-value"),
    ],
)
def test_a_readable_row_decides_a_value_as_both_readers_do(
    sent: int, constraint: dict[str, object], fits: bool
) -> None:
    # INVARIANT (C4): both readers hold a bound as a float and compare the sent value with it.
    schema = {"type": "integer", **constraint}
    assert _constraints_readable(schema, ("integer",)) is True
    value = model_params({"seed": str(sent)})["seed"]
    assert value_fits(max_tokens_rule(schema=schema), value) is fits
    document, gateway = _admitted("seed", str(sent), schema)
    if fits:
        assert set(document) == {"input", "spec"}
    else:
        assert document == refusal("routing_profile_mismatch")
    assert posts(gateway) == []


@pytest.mark.parametrize(
    "constraint",
    [
        pytest.param({"maximum": float("inf")}, id="infinite-maximum"),
        pytest.param({"minimum": float("-inf")}, id="negative-infinite-minimum"),
        pytest.param({"maximum": float("nan")}, id="nan-maximum"),
    ],
)
def test_a_bound_that_is_not_a_finite_float_is_unreadable(constraint: dict[str, object]) -> None:
    # WHY no ADMIT here: JSON carries no such number, but Python's `json` parses `Infinity` and
    # `NaN`; the SDK refuses such a row, so the Engine reads none.
    schema = {"type": "integer", **constraint}
    assert _constraints_readable(schema, ("integer",)) is False
    assert value_fits(max_tokens_rule(schema=schema), 1) is False


@pytest.mark.parametrize(
    ("sent", "schema"),
    [
        pytest.param(1, {"type": "integer", "enum": [True]}, id="enum-true-for-1"),
        pytest.param(1, {"type": "integer", "minimum": _HUGE}, id="huge-minimum"),
        pytest.param(1, {"type": ["integer", "integer"]}, id="duplicate-type"),
        pytest.param(_P53 + 1, {"type": "integer", "maximum": _P53 + 1}, id="max-held-as-2**53"),
        pytest.param(1, {"type": ["string", "integer"], "pattern": _DEEP}, id="pattern-too-deep"),
        pytest.param(1, {"type": "integer", "exclusiveMaximum": 1}, id="unknown-key"),
        pytest.param(1, {"type": "integer", "enum": []}, id="empty-enum"),
    ],
)
def test_a_router_run_over_such_a_row_ends_at_admit_with_no_classifier_or_chat_call(
    sent: int, schema: dict[str, object]
) -> None:
    definition, gateway = _scripted("seed", str(sent), schema)

    value, recorded = asyncio.run(run_block(gateway, block(definition)))

    assert getattr(value, "code", None) == "routing_profile_mismatch"
    assert posts(gateway) == []
    assert [call for call in recorded if call.is_provider] == []
