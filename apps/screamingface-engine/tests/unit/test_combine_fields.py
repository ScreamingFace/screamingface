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
from combine_golden_support import stage
from combine_support import context_text, run, spec_text

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.combine.ports import NoVotes, SpecInvalid, canonical_json

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


def _status_reason(outcome: Any, index: int) -> tuple[str, str | None]:
    row = _evidence(outcome)["members"][index]
    return (row["status"], row["reason"])


# --- json_object@1 ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"a": 1, "b": [2, 3]}', '{"a":1,"b":[2,3]}'),
        ('  {"b": "x", "a": null}  ', '{"a":null,"b":"x"}'),
        ('Sure:\n```json\n{"a": 1}\n```', '{"a":1}'),
        ('```json\n{"a": 1}\n```\nno, rather\n```json\n{"a": 2}\n```', '{"a":2}'),
        ("{}", "{}"),
        ('{"é": "ü"}', '{"é":"ü"}'),
        ('{"a":1,"a":2}', '{"a":2}'),
    ],
)
def test_json_object_reads_a_whole_or_fenced_object(text: str, expected: str) -> None:
    result = stage("json_object@1", text)
    assert (result.status, result.value) == ("voted", expected)


@pytest.mark.parametrize(
    "text",
    [
        "[1, 2]",
        '"text"',
        "7",
        "null",
        'Sure! Here it is: {"a": 1}',
        "",
        '{"a": NaN}',
        '{"a": 1e999}',
        '{"a":' * 65 + "1" + "}" * 65,
    ],
)
def test_json_object_rejects_anything_that_is_not_one_object(text: str) -> None:
    result = stage("json_object@1", text)
    assert (result.status, result.value) == ("not_json", None)


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


def test_all_members_unusable_fails_with_combine_no_votes() -> None:
    prose = ["Sure!", "Here it is.", "No JSON."]
    with pytest.raises(NoVotes):
        _run(pick_spec(3, step("by_field@1", order="max")), prose)
    with pytest.raises(NoVotes):
        _run(merge_spec(3, _MERGE_RULES[:1]), prose)
    # every member is JSON, but no member has the majority field
    with pytest.raises(NoVotes):
        _run(merge_spec(3, [{"field": "x", "rule": "majority", "normalize": None}]), _MERGE_TEXTS)
    with pytest.raises(NoVotes):
        _run(pick_spec(3, step("by_field@1", order="max")), ['{"a": 1}'] * 3)


# --- PM-10 ------------------------------------------------------------------------------------


def test_pick_tie_goes_to_author_order() -> None:
    texts = ['{"confidence": 0.9, "n": 1}', '{"confidence": 0.5}', '{"confidence": 0.9, "n": 3}']
    outcome = _run(pick_spec(3, step("by_field@1", order="max")), texts)
    assert outcome.output == texts[0]
    evidence = _evidence(outcome)
    assert evidence["tie"] is True
    assert evidence["chosen"] == ["member_1"]


# --- PM-15 ------------------------------------------------------------------------------------


def test_pick_equals_uses_declared_normalizer() -> None:
    texts = ['{"confidence": "Yes."}', '{"confidence": "no"}']

    def pick(value: str, normalize: str | None, spec_normalize: str | None) -> Any:
        select = step("by_field@1", order="equals", value=value, normalize=normalize)
        return _run(pick_spec(2, select, normalize=spec_normalize), texts)

    assert pick("yes", "text", "text@1").output == texts[0]
    assert pick("Yes.", "text", "text@1").output == texts[0]
    with pytest.raises(NoVotes):
        pick("yes", None, None)


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


def test_merge_output_has_only_declared_fields() -> None:
    texts = [json.dumps({"keep": 1, "extra": "x", "other": [1]}), '{"keep": 2, "more": 0}']
    outcome = _run(merge_spec(2, [{"field": "keep", "rule": "max"}]), texts)
    assert outcome.output == '{"keep":2}'


# --- PM-14 ------------------------------------------------------------------------------------


def test_from_member_not_json_gives_null_field_and_reason() -> None:
    rules = [{"field": "source", "rule": "from_member", "member": "member_2"}]
    texts = [_MERGE_TEXTS[0], "Sure! not json", _MERGE_TEXTS[2]]
    outcome = _run(merge_spec(3, rules), texts)
    assert outcome.output == '{"source":null}'
    evidence = _evidence(outcome)
    assert evidence["fields"][0]["result"] is None
    assert _status_reason(outcome, 1) == ("fail", "not_json")


def test_from_member_outside_the_spec_members_is_a_spec_error() -> None:
    rules = [{"field": "source", "rule": "from_member", "member": "member_9"}]
    with pytest.raises(SpecInvalid):
        _run(merge_spec(3, rules), _MERGE_TEXTS)


# --- PM-11 ------------------------------------------------------------------------------------


def test_merged_json_is_canonical() -> None:
    texts = ['{"z": "ü", "b": [1, 2], "a": "x"}', '{"a": "x", "b": [3], "z": "ü"}']
    rules = [
        {"field": "z", "rule": "majority", "normalize": None},
        {"field": "a", "rule": "majority", "normalize": "text"},
        {"field": "b", "rule": "union", "normalize": None},
    ]
    outputs = {_run(merge_spec(2, rules), texts).output for _ in range(100)}
    assert len(outputs) == 1
    (output,) = outputs
    assert output == canonical_json(json.loads(output))
    assert output == '{"a":"x","b":[1,2,3],"z":"ü"}'


# --- PM-6 (engine half) -----------------------------------------------------------------------


def test_projection_returns_only_the_field_values() -> None:
    texts = ['{"summary":"a"}', '{"summary":"b","x":1}', '{"x":2}']
    outcome = _run(project_spec(3, "summary"), texts)
    assert outcome.output == '{"member_1":"a","member_2":"b"}'
    evidence = _evidence(outcome)
    assert (evidence["kind"], evidence["reducer"]) == ("projection", "project")
    assert evidence["fields"] == [
        {
            "field": "summary",
            "rule": "project",
            "values": {"member_1": "a", "member_2": "b"},
            "result": None,
        }
    ]


def test_projection_with_no_member_field_fails_with_no_votes() -> None:
    with pytest.raises(NoVotes):
        _run(project_spec(2, "summary"), ['{"x":1}', '{"summary":null}'])


# --- model field ------------------------------------------------------------------------------


def test_model_field_takes_the_writer_text() -> None:
    rules = [{"field": "answer", "rule": "majority", "normalize": "text"}]
    rules.append({"field": "summary", "rule": "model"})
    outcome = _run(merge_spec(3, rules), _MERGE_TEXTS, {"writer_summary": "S."})
    assert outcome.output == '{"answer":"Paris.","summary":"S."}'
    summary = _evidence(outcome)["fields"][1]
    assert (summary["rule"], summary["result"]) == ("model", "S.")
    with pytest.raises(SpecInvalid):
        _run(merge_spec(3, rules), _MERGE_TEXTS)


# --- PM-D8 ------------------------------------------------------------------------------------


def test_large_member_json_is_too_large_and_skipped() -> None:
    huge = '{"answer": "' + "x" * (2 * 1024 * 1024) + '"}'
    texts = [_MERGE_TEXTS[0], huge, _MERGE_TEXTS[1]]
    outcome = _run(merge_spec(3, [{"field": "score", "rule": "max"}]), texts)
    assert outcome.output == '{"score":5}'
    assert _status_reason(outcome, 1) == ("fail", "too_large")


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
    with pytest.raises(NoVotes) as no_votes:
        _run(merge_spec(1, [{"field": "secretfield", "rule": "max"}]), texts)
    with pytest.raises(NoVotes) as no_match:
        pick = step("by_field@1", order="equals", value="SECRET-TARGET", normalize=None)
        _run(pick_spec(1, pick, normalize=None), ['{"confidence": "other"}'])
    for caught in (no_signal, no_votes, no_match):
        assert "SECRET" not in str(caught.value)
        assert "secretfield" not in str(caught.value)
    assert "field 1" in str(no_votes.value)


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
