"""One Model parameter value against its published Gateway row (C4 ADMIT, Unit 5.2).

FEATURE: Router Recipe extension. ADMIT checks each Router Model's parameter contract before any
I/O of the occurrence, as the SDK's E4c preflight does for a Gate member
(`_evaluation/model_parameters._validate_parameter`): the row exists, the Gateway forwards it, the
provider does not refuse it, and the value fits the schema the Gateway itself enforces.

INVARIANT: a row that cannot be read misfits; it is never repaired or read as permissive.
"""

from __future__ import annotations

import math
from typing import Any

import pytest

from screamingface_engine.world.parameter_contract import value_fits


def _rule(
    schema: object = None, *, status: object = "enabled", support: object = "supported"
) -> Any:
    return {
        "request_path": "x",
        "schema": {"type": "integer", "minimum": 1} if schema is None else schema,
        "provider": {"support": support, "source": "declared", "stale": False},
        "gateway": {"status": status, "projection": "direct"},
    }


# --- stages 1-3: the row, the Gateway, the provider ----------------------------------------------


def test_a_value_inside_an_enabled_supported_row_fits() -> None:
    assert value_fits(_rule(), 256) is True


def test_an_absent_row_misfits() -> None:
    assert value_fits(None, 256) is False


@pytest.mark.parametrize("status", ["disabled", "blocked", ""])
def test_a_row_the_gateway_does_not_forward_misfits(status: str) -> None:
    assert value_fits(_rule(status=status), 256) is False


def test_a_provider_refusal_misfits() -> None:
    assert value_fits(_rule(support="unsupported"), 256) is False


@pytest.mark.parametrize("support", ["conditional", "unknown", "supported"])
def test_provider_evidence_short_of_a_refusal_passes(support: str) -> None:
    # WHY: as the SDK's stage 3, only the provider's explicit "unsupported" refuses.
    assert value_fits(_rule(support=support), 256) is True


@pytest.mark.parametrize(
    "support",
    [
        pytest.param("maybe", id="invented"),
        pytest.param("Supported", id="case-variant"),
        pytest.param(" supported", id="padded"),
        pytest.param("", id="empty"),
        pytest.param(None, id="null"),
        pytest.param(True, id="boolean"),
        pytest.param(1, id="number"),
        pytest.param(["supported"], id="list"),
        pytest.param({"supported": True}, id="object"),
    ],
)
def test_a_support_value_outside_the_gateways_closed_vocabulary_misfits(support: object) -> None:
    # INVARIANT: the Gateway publishes exactly supported, conditional, unsupported or unknown
    # (its `ProviderSupport`); any other value or type is unreadable evidence, never permissive.
    assert value_fits(_rule(support=support), 256) is False


def test_a_row_without_provider_support_misfits() -> None:
    rule = _rule()
    del rule["provider"]["support"]

    assert value_fits(rule, 256) is False


@pytest.mark.parametrize("status", [True, None, ["enabled"], {"enabled": True}], ids=str)
def test_a_gateway_status_of_another_type_misfits(status: object) -> None:
    assert value_fits(_rule(status=status), 256) is False


@pytest.mark.parametrize(
    "rule",
    [
        pytest.param("x", id="not-an-object"),
        pytest.param({"schema": {"type": "integer"}, "provider": {}}, id="no-gateway"),
        pytest.param(
            {"schema": {"type": "integer"}, "gateway": {"status": "enabled"}, "provider": "x"},
            id="provider-not-an-object",
        ),
        pytest.param(_rule(schema="integer"), id="schema-not-an-object"),
        pytest.param(_rule(schema={"minimum": 1}), id="schema-without-type"),
        pytest.param(_rule(schema={"type": "decimal"}), id="unknown-type"),
        pytest.param(_rule(schema={"type": ["integer", 7]}), id="type-list-with-a-non-name"),
        pytest.param(_rule(schema={"type": "integer", "minimum": "1"}), id="text-bound"),
        pytest.param(_rule(schema={"type": "integer", "maximum": True}), id="boolean-bound"),
        pytest.param(_rule(schema={"type": "string", "maxLength": 0}), id="zero-max-length"),
        pytest.param(_rule(schema={"type": "string", "pattern": "^(x$"}), id="broken-pattern"),
        pytest.param(_rule(schema={"type": "string", "enum": "a"}), id="enum-not-a-list"),
        pytest.param(_rule(schema={"type": "array", "items": "string"}), id="items-not-an-object"),
        pytest.param(
            _rule(schema={"type": "array", "items": {"type": "decimal"}}), id="unknown-item-type"
        ),
        pytest.param(
            _rule(schema={"type": "array", "items": {"type": ["string"]}}), id="item-type-list"
        ),
        pytest.param(_rule(schema={"type": {"integer": 1}}), id="type-an-object"),
    ],
)
def test_a_row_that_cannot_be_read_misfits(rule: object) -> None:
    assert value_fits(rule, 1) is False


def test_a_row_without_provider_evidence_misfits() -> None:
    # WHY: the SDK reads `provider.support` as a required field of every row; absent, the
    # row is unreadable, not unknown evidence.
    rule = _rule()
    del rule["provider"]

    assert value_fits(rule, 256) is False


# --- stage 4: the value against the schema --------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "value", "fits"),
    [
        ("integer", 3, True),
        ("integer", 3.5, False),
        ("integer", True, False),
        ("number", 0.2, True),
        ("number", 2, True),
        ("number", False, False),
        ("boolean", True, True),
        ("boolean", 1, False),
        ("string", "END", True),
        ("string", 1, False),
        ("array", ["a"], True),
        ("object", {"a": 1}, True),
        ("object", ["a"], False),
    ],
)
def test_the_value_must_have_a_published_type(kind: str, value: object, fits: bool) -> None:
    assert value_fits(_rule({"type": kind}), value) is fits


def test_a_type_list_admits_any_listed_type() -> None:
    rule = _rule({"type": ["string", "array"]})

    assert value_fits(rule, "END") is True
    assert value_fits(rule, ["END"]) is True
    assert value_fits(rule, 1) is False


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_a_non_finite_number_misfits_even_unbounded(value: float) -> None:
    # WHY: the Gateway rejects every non-finite float first; json reads "NaN" as one.
    assert value_fits(_rule({"type": "number"}), value) is False


@pytest.mark.parametrize(("value", "fits"), [(0, False), (1, True), (10, True), (11, False)])
def test_bounds_are_inclusive(value: int, fits: bool) -> None:
    assert value_fits(_rule({"type": "integer", "minimum": 1, "maximum": 10}), value) is fits


def test_bounds_apply_to_numbers_only() -> None:
    assert value_fits(_rule({"type": ["integer", "string"], "minimum": 5}), "1") is True


@pytest.mark.parametrize(("value", "fits"), [("abc", True), ("abcd", False)])
def test_a_string_is_at_most_max_length(value: str, fits: bool) -> None:
    assert value_fits(_rule({"type": "string", "maxLength": 3}), value) is fits


@pytest.mark.parametrize(("value", "fits"), [("12", True), ("1abc", False), ("", False)])
def test_a_pattern_must_match_the_whole_string(value: str, fits: bool) -> None:
    assert value_fits(_rule({"type": "string", "pattern": "^[0-9]+$"}), value) is fits


@pytest.mark.parametrize(("value", "fits"), [("low", True), ("max", False)])
def test_an_enum_names_every_allowed_value(value: str, fits: bool) -> None:
    assert value_fits(_rule({"type": "string", "enum": ["low", "high"]}), value) is fits


@pytest.mark.parametrize(
    ("value", "fits"),
    [(["a", "b"], True), (["a", 1], False), ([], True)],
)
def test_array_items_have_the_item_type(value: list[object], fits: bool) -> None:
    assert value_fits(_rule({"type": "array", "items": {"type": "string"}}), value) is fits


def test_number_items_are_finite() -> None:
    rule = _rule({"type": "array", "items": {"type": "number"}})

    assert value_fits(rule, [0.5, 1]) is True
    assert value_fits(rule, [0.5, math.nan]) is False
