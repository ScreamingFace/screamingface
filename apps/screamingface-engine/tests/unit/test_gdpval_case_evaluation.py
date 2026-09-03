"""GDPval evaluation envelopes — the decode gate must be as strict as the write-time binders.

INVARIANT under test: `decode_case_evaluation` is the aggregate's ONLY door, and the binders
are never called on the read path. The aggregate keys checks on `evaluation.rubric_id` but
verdicts on `evidence.rubric_id`, so a schema-valid envelope whose nested records disagree
about identity would score quietly wrong — decode must refuse it, matching the discipline
`bind_rubric_evaluation` / `bind_case_evaluation` enforce at write time.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from screamingface_engine.benchmarks.gdpval.case_evaluation import (
    bind_case_evaluation,
    bind_rubric_evaluation,
    decode_case_evaluation,
)
from screamingface_engine.benchmarks.gdpval.records import CASE_SCHEMA, RUBRIC_SCHEMA
from screamingface_engine.benchmarks.gdpval.verdict import SCHEMA as VERDICT_SCHEMA


def _case_record(case_id: int = 1) -> dict[str, Any]:
    return {"schema": CASE_SCHEMA, "case_id": case_id, "output": "the deliverable"}


def _rubric_record(case_id: int = 1, rubric_id: int = 1) -> dict[str, Any]:
    return {
        "schema": RUBRIC_SCHEMA,
        "case_id": case_id,
        "rubric_id": rubric_id,
        "rubric_item": f"[2] criterion {rubric_id}",
    }


def _evidence(case_id: int = 1, rubric_id: int = 1, met: bool = True) -> dict[str, Any]:
    return {
        "schema": VERDICT_SCHEMA,
        "case_id": case_id,
        "rubric_id": rubric_id,
        "criteria_met": met,
        "valid": True,
    }


def _envelope(rubric_ids: tuple[int, ...] = (1, 2)) -> dict[str, Any]:
    rows = [
        bind_rubric_evaluation(
            1,
            _case_record() if index == 0 else None,
            _rubric_record(rubric_id=rubric_id),
            _evidence(rubric_id=rubric_id),
        )
        for index, rubric_id in enumerate(rubric_ids)
    ]
    return bind_case_evaluation(1, rows)


def test_decode_round_trips_what_the_binders_produced() -> None:
    decoded = decode_case_evaluation(_envelope(), 1)
    assert [row["rubric_id"] for row in decoded["rubric_evaluations"]] == [1, 2]
    assert decoded["case"]["output"] == "the deliverable"


def test_decode_rejects_a_duplicate_rubric_id() -> None:
    # WHY: a duplicated criterion collapses in the aggregate's check index while its two
    # verdicts both survive in the verdict index — the exact split-brain this gate exists for.
    envelope = copy.deepcopy(_envelope())
    second = envelope["rubric_evaluations"][1]
    second["rubric_id"] = 1
    second["rubric"]["rubric_id"] = 1
    second["evidence"]["rubric_id"] = 1
    with pytest.raises(ValueError, match="duplicate"):
        decode_case_evaluation(envelope, 1)


def test_decode_rejects_evidence_bound_to_another_criterion() -> None:
    # The confirmed exploit: `_checks` keys on the row's rubric_id, `_verdicts` on the
    # evidence's. Verified upstream to score 0.625 where the honest outcome is a failure.
    envelope = copy.deepcopy(_envelope())
    envelope["rubric_evaluations"][1]["evidence"]["rubric_id"] = 1
    with pytest.raises(ValueError, match="inconsistent"):
        decode_case_evaluation(envelope, 1)


def test_decode_rejects_a_rubric_record_from_another_criterion() -> None:
    envelope = copy.deepcopy(_envelope())
    envelope["rubric_evaluations"][1]["rubric"]["rubric_id"] = 1
    with pytest.raises(ValueError, match="inconsistent"):
        decode_case_evaluation(envelope, 1)


def test_decode_rejects_a_nested_record_from_another_case() -> None:
    envelope = copy.deepcopy(_envelope())
    envelope["rubric_evaluations"][0]["evidence"]["case_id"] = 2
    with pytest.raises(ValueError, match="inconsistent"):
        decode_case_evaluation(envelope, 1)


def test_decode_rejects_a_wrong_nested_schema() -> None:
    envelope = copy.deepcopy(_envelope())
    envelope["rubric_evaluations"][0]["evidence"]["schema"] = "something.else.v1"
    with pytest.raises(ValueError, match="inconsistent"):
        decode_case_evaluation(envelope, 1)


def test_decode_rejects_a_non_positive_rubric_id() -> None:
    envelope = copy.deepcopy(_envelope())
    first = envelope["rubric_evaluations"][0]
    first["rubric_id"] = 0
    first["rubric"]["rubric_id"] = 0
    first["evidence"]["rubric_id"] = 0
    with pytest.raises(ValueError, match="rubric_id"):
        decode_case_evaluation(envelope, 1)
