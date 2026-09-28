"""The one shared verdict parser — and the typed record that cannot drop its audit trail.

INVARIANT under test (OME-1099, born from OME-1023): every audit field on a verdict record
is a REQUIRED constructor argument. The regression this prevents: a new board's parser
silently omitting ``raw_output`` on valid verdicts, leaving a scored criterion with nothing
to re-read when a grade is disputed.

INVARIANT under test: merging the parsers changed no board's wire records. Each board's
schema string, reason vocabulary, and payload fields are byte-identical to the drifted
copies this module replaced — the shape declaration carries the differences, the parser
carries the work.
"""

from __future__ import annotations

import json
from dataclasses import MISSING, fields
from typing import Any, cast

import pytest

from screamingface_engine.benchmarks.spine.verdict import (
    Verdict,
    VerdictShape,
    parse_verdict,
    recovered_array,
    rubric_binding_key,
)

# The two real payload dialects, spelled the way the boards declare them.
ENUM_SHAPE = VerdictShape(
    schema="test.enum-verdict.v1",
    status_field="criterion_status",
    statuses=("MET", "UNMET"),
    explanation_required=True,
    reasons={
        "empty": "empty",
        "not_json": "invalid_json",
        "not_object": "invalid_shape",
        "bad_explanation": "invalid_shape",
        "missing_status": "invalid_shape",
        "bad_status": "invalid_status",
    },
)
BOOL_SHAPE = VerdictShape(
    schema="test.bool-verdict.v1",
    status_field="criteria_met",
    statuses=None,
    explanation_required=False,
    reasons={
        "empty": "empty judge reply",
        "not_json": "judge reply is not a JSON object",
        "not_object": "judge reply is not a JSON object",
        "missing_status": "judge reply lacks criteria_met",
        "bad_status": "judge reply criteria_met is not a JSON boolean",
    },
)


def _bool_bind(raw: str) -> dict[str, object]:
    return parse_verdict(
        raw,
        shape=BOOL_SHAPE,
        identity=(("case_id", 1), ("rubric_id", 2)),
        producer_id="judge-x",
    ).record()


# --- the typed record refuses to lose its audit trail ------------------------------------


def test_every_audit_field_is_a_required_constructor_argument() -> None:
    # INVARIANT: no field of the verdict record carries a default. A default on
    # `raw_output` is exactly the OME-1023 bug re-armed: `raw_output=""` is type-valid
    # with the wrong meaning, so the only safe default is none at all — omitting the
    # field must fail pyright at every call site (and TypeError at runtime).
    for field in fields(Verdict):
        assert field.default is MISSING and field.default_factory is MISSING, (
            f"Verdict.{field.name} has a default — an audit field a caller can silently drop"
        )


def test_constructing_a_verdict_without_the_raw_reply_fails() -> None:
    # The runtime floor of the type-level rule: pyright rejects the omission statically
    # (no default on the field), and the dataclass rejects it at runtime too.
    with pytest.raises(TypeError):
        cast(Any, Verdict)(
            schema="test.enum-verdict.v1",
            identity=(("case_id", 1),),
            producer_id="judge-x",
            valid=False,
            payload=(),
            reason="empty",
        )


def test_a_verdict_is_either_valid_or_carries_a_reason_never_both() -> None:
    with pytest.raises(ValueError):
        Verdict(
            schema="s",
            identity=(("case_id", 1),),
            producer_id="j",
            raw_output="raw",
            valid=True,
            payload=(("criteria_met", True),),
            reason="empty",
        )
    with pytest.raises(ValueError):
        Verdict(
            schema="s",
            identity=(("case_id", 1),),
            producer_id="j",
            raw_output="raw",
            valid=False,
            payload=(),
            reason=None,
        )


# --- one parser, each board's exact wire record ------------------------------------------


def test_the_enum_dialect_produces_dracos_exact_valid_record() -> None:
    raw = json.dumps({"explanation": "The requirement is present.", "criterion_status": "MET"})
    record = parse_verdict(
        raw,
        shape=ENUM_SHAPE,
        identity=(("case_id", 7), ("criterion_id", "actual-id"), ("sequence", 1)),
        producer_id="fixture-judge",
    ).record()
    assert record == {
        "schema": "test.enum-verdict.v1",
        "case_id": 7,
        "criterion_id": "actual-id",
        "sequence": 1,
        "producer_type": "model",
        "producer_id": "fixture-judge",
        "valid": True,
        "explanation": "The requirement is present.",
        "criterion_status": "MET",
        "raw_output": raw,
    }


def test_the_bool_dialect_produces_the_rubric_boards_exact_valid_record() -> None:
    raw = json.dumps({"explanation": "because", "criteria_met": False})
    assert _bool_bind(raw) == {
        "schema": "test.bool-verdict.v1",
        "case_id": 1,
        "rubric_id": 2,
        "producer_type": "model",
        "producer_id": "judge-x",
        "valid": True,
        "criteria_met": False,
        "explanation": "because",
        "raw_output": raw,
    }


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ("", "empty"),
        ("   ", "empty"),
        ("not json", "invalid_json"),
        ("[1, 2]", "invalid_shape"),
        ('{"criterion_status": "MET"}', "invalid_shape"),  # explanation missing
        ('{"explanation": 5, "criterion_status": "MET"}', "invalid_shape"),
        ('{"explanation": "x"}', "invalid_shape"),  # status missing
        ('{"explanation": "x", "criterion_status": "MAYBE"}', "invalid_status"),
    ],
)
def test_the_enum_dialect_keeps_dracos_reason_vocabulary(raw: str, reason: str) -> None:
    record = parse_verdict(
        raw, shape=ENUM_SHAPE, identity=(("case_id", 1),), producer_id="j"
    ).record()
    assert record["valid"] is False
    assert record["reason"] == reason
    # WHY: the reply is kept even when rejected — the rejection is only auditable
    # against what the judge actually said.
    assert record["raw_output"] == raw


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ("", "empty judge reply"),
        ("prose only", "judge reply is not a JSON object"),
        ("[1, 2]", "judge reply is not a JSON object"),
        ('{"explanation": "x"}', "judge reply lacks criteria_met"),
        (
            '{"explanation": "x", "criteria_met": "true"}',
            "judge reply criteria_met is not a JSON boolean",
        ),
        (
            '{"explanation": "x", "criteria_met": 1}',
            "judge reply criteria_met is not a JSON boolean",
        ),
    ],
)
def test_the_bool_dialect_keeps_gdpvals_reason_vocabulary(raw: str, reason: str) -> None:
    # INVARIANT: only a REAL JSON boolean counts — "true" and 1 stay invalid replies,
    # exactly as the reference grade_sample loops on `label is True or label is False`.
    record = _bool_bind(raw)
    assert record["valid"] is False
    assert record["reason"] == reason


def test_fenced_and_prose_wrapped_json_is_recovered_with_original_bytes_kept() -> None:
    raw = 'Here is my verdict:\n```json\n{"explanation": "ok", "criteria_met": true}\n```'
    record = _bool_bind(raw)
    assert record["valid"] is True
    assert record["criteria_met"] is True
    # INVARIANT: the ORIGINAL bytes are the audit trail — persisting the fence-stripped
    # parse would hide exactly the lossy-parse case the trail exists to expose.
    assert record["raw_output"] == raw


def test_a_non_string_explanation_on_a_valid_bool_verdict_becomes_empty_text() -> None:
    record = _bool_bind('{"explanation": 5, "criteria_met": true}')
    assert record["valid"] is True
    assert record["explanation"] == ""


def test_the_parser_never_trusts_identity_the_judge_claims() -> None:
    raw = json.dumps({"explanation": "x", "criteria_met": True, "case_id": 999, "rubric_id": 888})
    record = _bool_bind(raw)
    assert record["case_id"] == 1
    assert record["rubric_id"] == 2


def test_a_blank_producer_id_is_refused() -> None:
    # WHY: the verdict record is evidence; evidence with no attributable producer
    # cannot be audited after the fact.
    with pytest.raises(ValueError):
        parse_verdict("{}", shape=BOOL_SHAPE, identity=(("case_id", 1),), producer_id="  ")


# --- shared rubric wiring (healthbench and gdpval were byte-identical) -------------------


def test_rubric_binding_key_decodes_case_and_rubric_ids() -> None:
    assert rubric_binding_key("12:34") == (12, 34)


@pytest.mark.parametrize("value", ["", "12", "12:", ":34", "a:b", "0:1", "1:0", "-1:2"])
def test_rubric_binding_key_rejects_malformed_or_non_positive(value: str) -> None:
    with pytest.raises(ValueError):
        rubric_binding_key(value)


# --- the check surface's array recovery shares the same JSON-recovery primitive ----------


def test_recovered_array_reads_a_fenced_ordinal_reply() -> None:
    reply = '```json\n[{"id": 1, "status": "MET"}]\n```'
    assert recovered_array(reply) == [{"id": 1, "status": "MET"}]


def test_recovered_array_refuses_replies_with_no_array() -> None:
    assert recovered_array("no verdicts here") is None
    assert recovered_array("") is None
