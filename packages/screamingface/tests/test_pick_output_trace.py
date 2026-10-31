"""The trace mode of a Pick with ``output=`` (E4b pick-output, review P1 #6).

FEATURE: a Pick with ``output=`` returns one field of the winner's reply, a new value, so its
``reduce`` trace entry says ``mode: "compute"``, as the evidence says ``built`` and
``result.member_id`` is None (e4a answer-record AR-3: a compute result has no member id).
INVARIANT: a Pick without ``output=`` keeps ``mode: "select"``; the evidence bytes do not change.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from _combine_contract import COMBINE_CONTRACT, requires_engine_app

import screamingface as sf
from screamingface._case_views import case_trace
from screamingface._evaluation.combine_evidence import decode_combine_evidence
from screamingface.case_result import CaseOperation
from screamingface.combine_evidence import CombineEvidence


def _evidence(name: str) -> CombineEvidence:
    cases: dict[str, Any] = json.loads(
        (COMBINE_CONTRACT / "evidence_cases.json").read_text(encoding="utf-8")
    )
    decoded = decode_combine_evidence(cases[name], f"Engine evidence {name}")
    assert decoded is not None
    return decoded


def _reduce_mode(evidence: CombineEvidence) -> object:
    case = sf.CaseResult(
        case_id=1,
        input="Question 1",
        output="x",
        finish_reason="stop",
        grade=sf.CaseGrade(method="fixture", score=1.0, metrics={}, checks=()),
        failures=(),
        metadata={},
        operations=[CaseOperation("op_synthesis_1", "42", "stop", None, combine=evidence)],
    )
    (entry,) = [entry for entry in case_trace(case, None) if entry.kind == "reduce"]
    return entry.data["mode"]


@requires_engine_app
@pytest.mark.parametrize("name", ["pick_output", "pick_output_missing"])
def test_a_pick_with_output_traces_as_compute(name: str) -> None:
    # WHY: the result is the winner's field, not the winner's text; `output_missing` is the
    # abstain only a Pick with output= has.
    assert _reduce_mode(_evidence(name)) == "compute"


@requires_engine_app
@pytest.mark.parametrize("name", ["pick", "argmax_cost_min"])
def test_a_pick_without_output_still_traces_as_select(name: str) -> None:
    assert _reduce_mode(_evidence(name)) == "select"
