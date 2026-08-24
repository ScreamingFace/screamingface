"""Turning a raw judge reply into a verdict — and refusing to guess when it is garbage.

INVARIANT under test: only a REAL JSON boolean counts as a verdict. A string "true" or a 1 is an
invalid reply, never a lenient yes — a judge that cannot follow the reply format cannot be
trusted to have followed the grading instruction either.

INVARIANT under test: the Engine stamps ``case_id`` and ``rubric_id``. The judge never sees them
and cannot be trusted to echo them, so anything it claims about identity is ignored.
"""

from __future__ import annotations

import json

import pytest

from screamingface_engine.benchmarks.gdpval.verdict import SCHEMA, bind, binding_key


def _reply(met: object, explanation: str = "because") -> str:
    return json.dumps({"explanation": explanation, "criteria_met": met})


def test_binding_key_decodes_case_and_rubric_ids() -> None:
    assert binding_key("12:34") == (12, 34)


@pytest.mark.parametrize("value", ["", "12", "12:", ":34", "a:b", "0:1", "1:0", "-1:2"])
def test_binding_key_rejects_malformed_or_non_positive(value: str) -> None:
    with pytest.raises(ValueError):
        binding_key(value)


def test_a_true_verdict_is_valid() -> None:
    record = bind(_reply(True), case_id=1, rubric_id=2, producer_id="judge-x")
    assert record["valid"] is True
    assert record["criteria_met"] is True
    assert record["schema"] == SCHEMA


def test_a_false_verdict_is_valid() -> None:
    record = bind(_reply(False), case_id=1, rubric_id=2, producer_id="judge-x")
    assert record["valid"] is True
    assert record["criteria_met"] is False


@pytest.mark.parametrize("met", ["true", "yes", 1, 0, None, [], {}])
def test_a_non_boolean_verdict_is_invalid(met: object) -> None:
    # WHY strict: a lenient cast would turn "the judge misunderstood the format" into a scored
    # answer, which is worse than failing the criterion loudly.
    record = bind(_reply(met), case_id=1, rubric_id=2, producer_id="judge-x")
    assert record["valid"] is False
    assert record["reason"]


@pytest.mark.parametrize("raw", ["", "   ", "not json", "[1,2]", '{"criteria_met": true'])
def test_unparseable_replies_are_invalid(raw: str) -> None:
    record = bind(raw, case_id=1, rubric_id=2, producer_id="judge-x")
    assert record["valid"] is False


def test_an_invalid_reply_keeps_the_raw_output_for_audit() -> None:
    record = bind("garbage", case_id=1, rubric_id=2, producer_id="judge-x")
    assert record["raw"] == "garbage"


def test_the_engine_stamps_identity_and_ignores_what_the_judge_claims() -> None:
    raw = json.dumps({"explanation": "x", "criteria_met": True, "case_id": 999, "rubric_id": 888})
    record = bind(raw, case_id=1, rubric_id=2, producer_id="judge-x")
    assert record["case_id"] == 1
    assert record["rubric_id"] == 2


def test_bind_rejects_non_positive_engine_ids() -> None:
    with pytest.raises(ValueError):
        bind(_reply(True), case_id=0, rubric_id=1, producer_id="judge-x")
    with pytest.raises(ValueError):
        bind(_reply(True), case_id=1, rubric_id=0, producer_id="judge-x")


def test_bind_requires_a_producer_id() -> None:
    # WHY: the verdict record is evidence. A verdict with no attributable producer cannot be
    # audited after the fact.
    with pytest.raises(ValueError):
        bind(_reply(True), case_id=1, rubric_id=2, producer_id="  ")
