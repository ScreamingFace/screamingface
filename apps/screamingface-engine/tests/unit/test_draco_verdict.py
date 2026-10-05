"""DRACO criterion-verdict binding behavior."""

from __future__ import annotations

import json

from screamingface_engine.benchmarks.draco import verdict as criterion_verdict


def _bind(raw: str, *, case_id: int, criterion_id: str) -> dict[str, object]:
    return criterion_verdict.build_evidence_record(
        raw,
        case_id=case_id,
        criterion_id=criterion_id,
        sequence=1,
        producer_id="fixture-judge",
    )


def test_a_valid_reply_is_bound_to_the_engine_known_criterion() -> None:
    raw = json.dumps(
        {
            "criterion_id": "model-invented-id",
            "explanation": "The requirement is present.",
            "criterion_status": "MET",
        }
    )
    record = _bind(
        raw,
        case_id=7,
        criterion_id="actual-id",
    )

    assert record == {
        "schema": "screamingface.criterion-verdict.v1",
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


def test_fenced_or_prefixed_json_is_accepted_like_the_reference_harness() -> None:
    record = _bind(
        'Here is the verdict:\n```json\n{"explanation":"No error.",'
        '"criterion_status":"UNMET"}\n```',
        case_id=3,
        criterion_id="negative-1",
    )

    assert record["valid"] is True
    assert record["criterion_id"] == "negative-1"
    assert record["criterion_status"] == "UNMET"


def test_invalid_replies_become_diagnostic_records_instead_of_command_failures() -> None:
    assert _bind("", case_id=1, criterion_id="a1") == {
        "schema": "screamingface.criterion-verdict.v1",
        "case_id": 1,
        "criterion_id": "a1",
        "sequence": 1,
        "producer_type": "model",
        "producer_id": "fixture-judge",
        "valid": False,
        "reason": "empty",
        "raw_output": "",
    }
    assert _bind("not json", case_id=1, criterion_id="a1")["reason"] == "invalid_json"
    assert (
        _bind(
            '{"explanation":"x","criterion_status":"MAYBE"}',
            case_id=1,
            criterion_id="a1",
        )["reason"]
        == "invalid_status"
    )
    assert (
        _bind('{"criterion_status":"MET"}', case_id=1, criterion_id="a1")["reason"]
        == "invalid_shape"
    )


def test_the_internal_binding_key_preserves_colons_in_criterion_ids() -> None:
    assert criterion_verdict.evidence_record_key("12:3:section:criterion") == (
        12,
        3,
        "section:criterion",
    )
