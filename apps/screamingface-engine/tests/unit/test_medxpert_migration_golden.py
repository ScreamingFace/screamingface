"""Golden replay for the medxpert → serving-spine migration (OME-1236).

INVARIANT: an expression addressed to the current revision must resolve to
byte-identical protocol before and after the extraction. Every literal below was
captured from the pre-migration board at the head of this branch's base; if any
assertion here fails, the migration changed the exam, not just its plumbing.
"""

from __future__ import annotations

import json
from pathlib import Path

from screamingface_engine.benchmarks.contract import encode_candidate_invocation
from screamingface_engine.benchmarks.medxpert.definition import (
    AGGREGATE_ROUTE,
    CASE_EVALUATION_ROUTE,
    CASES_ROUTE,
    CHECK_ROUTE,
    REVISION,
    ROUTE_PREFIX,
)
from screamingface_engine.benchmarks.medxpert.prepare import emit
from screamingface_engine.benchmarks.medxpert.runtime import _cases, _check, preflight
from url4.core.errors import ResolutionError
from url4.peer.server import Request

# Captured 2026-09-21 from the pre-migration board (base of this branch).
_GOLDEN_REVISION = "791a7d5b2e961f1c"

_OPTIONS = {"A": "aspirin", "B": "heparin", "C": "warfarin", "D": "apixaban", "E": "alteplase"}
_QUESTION = "Which agent is indicated? Answer Choices: " + " ".join(
    f"({letter}) {label}" for letter, label in _OPTIONS.items()
)


def _root(tmp_path: Path) -> Path:
    row = {
        "id": "Text-0",
        "question": _QUESTION,
        "options": _OPTIONS,
        "label": "E",
        "medical_task": "Diagnosis",
        "body_system": "Cardiovascular",
        "question_type": "Reasoning",
    }
    emit([row], tmp_path)
    return tmp_path


class TestRevisionAndRoutes:
    def test_revision_is_byte_identical_to_the_pre_migration_exam(self) -> None:
        assert REVISION == _GOLDEN_REVISION

    def test_routes_resolve_at_the_recorded_addresses(self) -> None:
        assert ROUTE_PREFIX == f"/benchmarks/medxpert/{_GOLDEN_REVISION}"
        assert CASES_ROUTE == f"{ROUTE_PREFIX}/cases"
        assert CHECK_ROUTE == f"{ROUTE_PREFIX}/check"
        assert CASE_EVALUATION_ROUTE == f"{ROUTE_PREFIX}/case-evaluation"
        assert AGGREGATE_ROUTE == f"{ROUTE_PREFIX}/aggregate"


class TestCheckRecordBytes:
    def test_check_record_is_byte_identical(self, tmp_path: Path) -> None:
        # The exact string the pre-migration `_check` produced for this fixture,
        # including field ORDER — the envelope participates in recorded protocol.
        handler = _check(_root(tmp_path))
        commit = encode_candidate_invocation("the answer is (E) alteplase", "stop", None)
        context = json.dumps({"reasoning": "I think E.", "commit": commit})

        record = handler(Request(path="/t", context=context, intent="1", params={}))

        assert record == (
            '{"schema":"screamingface.medxpert-check.v1","case_id":1,"attempt":1,'
            '"answer":"E","answered":true,"status":"completed","refusal":null,'
            '"finish_reason":"stop","commit_output":"the answer is (E) alteplase",'
            '"reasoning":"I think E.","execution":null}'
        )


class TestServedCases:
    def test_served_rows_are_byte_identical(self, tmp_path: Path) -> None:
        served_bytes = _cases(_root(tmp_path))()

        assert served_bytes == (
            '[{"id":1,"case_id":"1","input":"' + _QUESTION + '",'
            '"cot_prompt":"Q: ' + _QUESTION + "\\nA: Let's think step by step.\","
            '"trigger":"Therefore, among A through E, the answer is"}]'
        )


class TestPreflightErrorClass:
    def test_a_missing_answer_record_is_a_definition_error(self, tmp_path: Path) -> None:
        """Pin medxpert's per-board deviation: a broken bundle is a DEFINITION error.

        WHY the direct `preflight` call (review of this PR): through `serve_cases`,
        a missing answer record trips `_build_rows`' own raise before the preflight
        ever runs, so the declaration's error class was unreachable from that path
        and its deletion survived the whole suite. This is the one test that dies
        if `preflight` stops raising `benchmark_definition_error`.
        """
        import pytest

        with pytest.raises(ResolutionError) as caught:
            preflight(_root(tmp_path), (9,))

        assert caught.value.code == "benchmark_definition_error"
