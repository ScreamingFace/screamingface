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
    # WHY the key is `raw_output`: the aggregate's evidence projection reads that name when it
    # renders a rejected verdict into the report. A different key here would drop the audit
    # trail silently — the reply would be recorded as invalid with nothing to inspect.
    record = bind("garbage", case_id=1, rubric_id=2, producer_id="judge-x")
    assert record["raw_output"] == "garbage"


@pytest.mark.parametrize("met", [True, False])
def test_a_valid_verdict_keeps_the_raw_reply_for_audit(met: bool) -> None:
    # INVARIANT: EVERY verdict is auditable against the reply that produced it, not only the
    # rejected ones. A scored criterion whose evidence carries raw_output == "" is
    # unfalsifiable — a reviewer disputing a verdict on a paid run has nothing to re-read.
    # HealthBench and DRACO both persist the raw reply on the valid branch; this pins GDPval
    # to the same engine convention (OME-1023).
    raw = _reply(met)
    record = bind(raw, case_id=1, rubric_id=2, producer_id="judge-x")
    assert record["valid"] is True
    assert record["raw_output"] == raw


def test_a_valid_fenced_reply_keeps_the_original_bytes_not_the_stripped_text() -> None:
    # WHY the ORIGINAL bytes: the audit question is "what did the judge actually say", and
    # fence-stripping is part of OUR parse — persisting the stripped text would hide exactly
    # the lossy-parse case the audit trail exists to expose.
    raw = f"```json\n{_reply(True)}\n```"
    record = bind(raw, case_id=1, rubric_id=2, producer_id="judge-x")
    assert record["valid"] is True
    assert record["raw_output"] == raw


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


# --- reply shapes the judge actually produces --------------------------------------------------


def test_a_fenced_json_reply_is_accepted() -> None:
    # WHY: measured against the pinned judge (gemini-3.1-pro-preview) on 2026-08-25 — it wraps
    # its JSON in a ```json fence. DRACO hit the same behaviour with the same model and strips
    # fences for exactly this reason. Rejecting these would fail every case at rubric 1.
    raw = '```json\n{\n  "explanation": "No SOAP headings.",\n  "criteria_met": false\n}\n```'
    record = bind(raw, case_id=1, rubric_id=1, producer_id="judge-x")
    assert record["valid"] is True
    assert record["criteria_met"] is False


def test_a_bare_fence_without_a_language_tag_is_accepted() -> None:
    raw = '```\n{"explanation": "ok", "criteria_met": true}\n```'
    assert bind(raw, case_id=1, rubric_id=1, producer_id="j")["criteria_met"] is True


def test_json_preceded_by_prose_is_recovered() -> None:
    # WHY a fallback rather than strictness: the alternative is burning two retries and failing
    # the Case on a reply that plainly contains the verdict.
    raw = 'Here is my assessment:\n{"explanation": "fine", "criteria_met": true}'
    assert bind(raw, case_id=1, rubric_id=1, producer_id="j")["criteria_met"] is True


def test_fence_stripping_does_not_soften_the_boolean_rule() -> None:
    # INVARIANT: recovering the JSON is not the same as accepting a truthy value. A fenced
    # reply whose criteria_met is a STRING is still invalid.
    raw = '```json\n{"explanation": "x", "criteria_met": "true"}\n```'
    record = bind(raw, case_id=1, rubric_id=1, producer_id="j")
    assert record["valid"] is False


def test_a_fence_containing_no_json_is_still_invalid() -> None:
    raw = "```\nI could not determine this.\n```"
    assert bind(raw, case_id=1, rubric_id=1, producer_id="j")["valid"] is False
