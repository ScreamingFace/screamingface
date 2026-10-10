"""Pick and merge read JSON members by declared field rules (OME-1289 E4a, unit 9).

FEATURE: members that return JSON are joined by declared rules, not rewritten by a model.
STORY: as a researcher, Pick returns the chosen member's own JSON byte for byte, and Merge returns
one canonical JSON object with exactly the declared fields, each built by its own rule.
INVARIANT defended: a member that is not a JSON object is skipped and reported (``not_json``); no
rule echoes member text in an error; field readings hold JSON values only.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from combine_fields_support import merge_spec, pick_spec, project_spec, step
from combine_flow_support import find_builtin
from combine_support import context_text, run, spec_text

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.combine.evidence import ResultRecord
from screamingface_engine.combine.ports import SpecInvalid

_PICK_TEXTS = (
    '{"a": 1, "confidence": 0.4}',
    '{"a": 2, "confidence": 0.9}',
    '{"a": 3, "confidence": 0.7}',
)
_MERGE_TEXTS = (
    '{"answer":"Paris.","score":3,"source":"wiki","synonyms":["MI","heart attack"]}',
    '{"answer":"paris","score":5,"source":"book",'
    '"synonyms":["heart attack","myocardial infarction"]}',
    '{"answer":"Lyon","score":"high","source":"web"}',
)
_MERGE_RULES = [
    {"field": "answer", "rule": "majority", "normalize": "text"},
    {"field": "score", "rule": "max"},
    {"field": "source", "rule": "from_member", "member": "member_2"},
    {"field": "synonyms", "rule": "union", "normalize": "text"},
]


def _run(
    spec: Any, texts: tuple[str, ...] | list[str], signals: dict[str, str] | None = None
) -> Any:
    return run(spec_text(spec), context_text(list(texts), signals), registry=BUILTIN_OPERATORS)


def _evidence(outcome: Any) -> dict[str, Any]:
    return outcome.evidence.model_dump(by_alias=True)


def _abstained(outcome: Any) -> dict[str, Any]:
    """Assert the outcome is a ``no_votes`` abstain with no chosen member; return its evidence."""
    evidence = outcome.evidence
    assert outcome.output == ""
    assert evidence.result == ResultRecord(
        member_id=None, value=None, status="abstain", reason="no_votes"
    )
    assert (evidence.chosen, evidence.built) == ([], False)
    return _evidence(outcome)


def _status_reason(outcome: Any, index: int) -> tuple[str, str | None]:
    row = _evidence(outcome)["members"][index]
    return (row["status"], row["reason"])


# --- PM-1 / OP-15 -----------------------------------------------------------------------------


def test_pick_max_min_equals_returns_member_json_byte_for_byte() -> None:
    biggest = _run(pick_spec(3, step("by_field@1", order="max")), _PICK_TEXTS)
    assert biggest.output == '{"a": 2, "confidence": 0.9}'
    smallest = _run(pick_spec(3, step("by_field@1", order="min")), _PICK_TEXTS)
    assert smallest.output == _PICK_TEXTS[0]
    equal = _run(
        pick_spec(3, step("by_field@1", order="equals", value="0.7", normalize="numeric")),
        _PICK_TEXTS,
    )
    assert equal.output == _PICK_TEXTS[2]
    evidence = _evidence(biggest)
    assert evidence["fields"] == [
        {
            "field": "confidence",
            "rule": "values",
            "values": {"member_1": "0.4", "member_2": "0.9", "member_3": "0.7"},
            "result": None,
        }
    ]
    assert evidence["operators"] == ["json_field@1", "numeric@1", "values@1", "by_field@1"]
    assert (evidence["kind"], evidence["reducer"], evidence["built"]) == ("answer", "pick", False)
    assert evidence["chosen"] == ["member_2"]


# --- PM-2 -------------------------------------------------------------------------------------


def test_non_json_member_is_skipped_and_reported() -> None:
    texts = [_PICK_TEXTS[0], 'Sure! Here it is: {"confidence": 1}', _PICK_TEXTS[2]]
    picked = _run(pick_spec(3, step("by_field@1", order="max")), texts)
    assert picked.output == _PICK_TEXTS[2]
    assert _status_reason(picked, 1) == ("fail", "not_json")
    merged = _run(merge_spec(3, _MERGE_RULES[:2]), [_MERGE_TEXTS[0], texts[1], _MERGE_TEXTS[2]])
    assert json.loads(merged.output) == {"answer": "Paris.", "score": 3}
    assert _status_reason(merged, 1) == ("fail", "not_json")


# --- PM-9 -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("spec", "texts"),
    [
        (merge_spec(3, [{"field": "x", "rule": "majority", "normalize": None}]), _MERGE_TEXTS),
        (merge_spec(3, [{"field": "source", "rule": "max"}]), _MERGE_TEXTS),
        (merge_spec(3, [{"field": "answer", "rule": "union", "normalize": None}]), _MERGE_TEXTS),
        (project_spec(2, "summary"), ('{"x":1}', '{"summary":null}')),
    ],
    ids=["majority", "max", "union", "projection"],
)
def test_merge_and_projection_without_usable_value_abstain(
    spec: Any, texts: tuple[str, ...]
) -> None:
    """AB#4: a reduce that finds no usable value abstains; no field readings are kept (F6)."""
    evidence = _abstained(_run(spec, texts))
    assert evidence["fields"] is None
    assert evidence["dropped"] == 0
    assert {row["status"] for row in evidence["members"]} == {"answered"}


def test_by_field_equals_that_finds_nothing_abstains_and_keeps_the_values() -> None:
    """AB#4 and F6: a select raise keeps the values@1 reading of the compared field."""
    select = step("by_field@1", order="equals", value="0.1", normalize="numeric")
    evidence = _abstained(_run(pick_spec(3, select), _PICK_TEXTS))
    assert evidence["fields"] == [
        {
            "field": "confidence",
            "rule": "values",
            "values": {"member_1": "0.4", "member_2": "0.9", "member_3": "0.7"},
            "result": None,
        }
    ]
    assert evidence["dropped"] == 0
    assert {row["status"] for row in evidence["members"]} == {"answered"}


# --- PM-3 / PM-4 / PM-5 / PM-13 ---------------------------------------------------------------

_MERGED = (
    '{"answer":"Paris.","score":5,"source":"book",'
    '"synonyms":["MI","heart attack","myocardial infarction"]}'
)


def test_merge_rules_majority_max_from_member_union() -> None:
    outcome = _run(merge_spec(3, _MERGE_RULES), _MERGE_TEXTS)
    assert outcome.output == _MERGED
    evidence = _evidence(outcome)
    assert (evidence["kind"], evidence["built"], evidence["chosen"]) == ("answer", True, [])
    assert evidence["operators"] == ["json_object@1", "field_rules@1", "built@1"]
    assert evidence["fields"] == [
        {
            "field": "answer",
            "rule": "majority",
            "values": {"member_1": "Paris.", "member_2": "paris", "member_3": "Lyon"},
            "result": "Paris.",
        },
        {
            "field": "score",
            "rule": "max",
            "values": {"member_1": 3, "member_2": 5, "member_3": "high"},
            "result": 5,
        },
        {
            "field": "source",
            "rule": "from_member",
            "values": {"member_1": "wiki", "member_2": "book", "member_3": "web"},
            "result": "book",
        },
        {
            "field": "synonyms",
            "rule": "union",
            "values": {
                "member_1": ["MI", "heart attack"],
                "member_2": ["heart attack", "myocardial infarction"],
            },
            "result": ["MI", "heart attack", "myocardial infarction"],
        },
    ]


# --- PM-14 ------------------------------------------------------------------------------------


def test_from_member_not_json_gives_null_field_and_reason() -> None:
    rules = [{"field": "source", "rule": "from_member", "member": "member_2"}]
    texts = [_MERGE_TEXTS[0], "Sure! not json", _MERGE_TEXTS[2]]
    outcome = _run(merge_spec(3, rules), texts)
    assert outcome.output == '{"source":null}'
    # a null from_member is a value, not an abstain
    assert outcome.evidence.result.status == "answered"
    evidence = _evidence(outcome)
    assert evidence["fields"][0]["result"] is None
    assert _status_reason(outcome, 1) == ("fail", "not_json")


# --- args bounds and messages -----------------------------------------------------------------


def test_field_rules_takes_at_most_64_fields() -> None:
    descriptor = find_builtin("field_rules@1")
    rules = [{"field": f"f{index}", "rule": "max"} for index in range(65)]
    descriptor.check_args({"fields": rules[:64]})
    with pytest.raises(SpecInvalid):
        descriptor.check_args({"fields": rules})


def test_failures_name_the_rule_and_never_echo_values() -> None:
    texts = ['{"secretfield": "SECRET-TEXT"}']
    with pytest.raises(SpecInvalid) as no_signal:
        _run(merge_spec(1, [{"field": "secretfield", "rule": "model"}]), texts)
    assert "SECRET" not in str(no_signal.value)
    assert "secretfield" not in str(no_signal.value)
    merge = _abstained(_run(merge_spec(1, [{"field": "secretfield", "rule": "max"}]), texts))
    # WHY not "members": they carry the extracted values by design (evidence.py)
    assert "SECRET" not in json.dumps({k: v for k, v in merge.items() if k != "members"})
    pick = step("by_field@1", order="equals", value="SECRET-TARGET", normalize=None)
    target = _abstained(_run(pick_spec(1, pick, normalize=None), ['{"confidence": "other"}']))
    assert "SECRET" not in json.dumps(target)


def test_a_non_finite_number_from_another_extractor_is_a_spec_error() -> None:
    # whole@1 hands the raw reply on, so an infinite number (1e999) reaches the field operator
    for spec in (
        merge_spec(1, [{"field": "x", "rule": "max"}], extract="whole@1"),
        project_spec(1, "x"),
    ):
        spec["extract"] = step("whole@1")
        with pytest.raises(SpecInvalid, match="needs JSON object values") as caught:
            _run(spec, ['{"x": 1e999}'])
        assert "1e999" not in str(caught.value)
