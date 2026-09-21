"""Golden replay for the contracteval → serving-spine migration (OME-1236).

INVARIANT: an expression addressed to the current revision must resolve to
byte-identical protocol before and after the extraction. Every literal below was
captured from the pre-migration board at the head of this branch's base; if any
assertion here fails, the migration changed the exam, not just its plumbing.
"""

from __future__ import annotations

import json
from pathlib import Path

from screamingface_engine.benchmarks.contract import encode_candidate_invocation
from screamingface_engine.benchmarks.contracteval.definition import (
    AGGREGATE_ROUTE,
    CASE_EVALUATION_ROUTE,
    CASES_ROUTE,
    CHECK_ROUTE,
    REVISION,
    ROUTE_PREFIX,
)
from screamingface_engine.benchmarks.contracteval.prepare import emit
from screamingface_engine.benchmarks.contracteval.runtime import _cases, _check
from url4.peer.server import Request

# Captured 2026-09-21 from the pre-migration board (base of this branch).
_GOLDEN_REVISION = "f9a076a10a6ae4c6"

_GOLD_SPAN = "This Agreement is governed by Delaware law."


def _root(tmp_path: Path) -> Path:
    row = {
        "id": "Doc__Governing Law",
        "title": "Doc",
        "context": f"1. Governing Law. {_GOLD_SPAN}",
        "question": "Which law governs?",
        "answers": {"text": [_GOLD_SPAN], "answer_start": [0]},
    }
    emit([row], tmp_path)
    return tmp_path


class TestRevisionAndRoutes:
    def test_revision_is_byte_identical_to_the_pre_migration_exam(self) -> None:
        assert REVISION == _GOLDEN_REVISION

    def test_routes_resolve_at_the_recorded_addresses(self) -> None:
        assert ROUTE_PREFIX == f"/benchmarks/contracteval/{_GOLDEN_REVISION}"
        assert CASES_ROUTE == f"{ROUTE_PREFIX}/cases"
        assert CHECK_ROUTE == f"{ROUTE_PREFIX}/check"
        assert CASE_EVALUATION_ROUTE == f"{ROUTE_PREFIX}/case-evaluation"
        assert AGGREGATE_ROUTE == f"{ROUTE_PREFIX}/aggregate"


class TestCheckRecordBytes:
    def test_check_record_is_byte_identical(self, tmp_path: Path) -> None:
        # The exact string the pre-migration `_check` produced for this fixture,
        # including field ORDER — the envelope participates in recorded protocol.
        handler = _check(_root(tmp_path))
        context = encode_candidate_invocation(f"The clause reads: {_GOLD_SPAN}", "stop", None)

        record = handler(Request(path="/t", context=context, intent="1", params={}))

        assert record == (
            '{"schema":"screamingface.contracteval-check.v1","case_id":1,"attempt":1,'
            '"correct":true,"is_positive":true,"abstained":false,"jaccard":0.7,'
            '"status":"completed","refusal":null,"finish_reason":"stop",'
            '"output":"The clause reads: This Agreement is governed by Delaware law.",'
            '"execution":null}'
        )


class TestServedCases:
    def test_served_rows_keep_shape_and_compact_bytes(self, tmp_path: Path) -> None:
        served_bytes = _cases(_root(tmp_path))()

        served = json.loads(served_bytes)
        assert [list(row) for row in served] == [["id", "case_id", "input"]]
        assert served[0]["id"] == 1
        assert served[0]["case_id"] == "1"
        # INVARIANT: compact separators, no ASCII escaping — the payload's exact
        # formatting is part of the recorded protocol.
        assert served_bytes == json.dumps(served, ensure_ascii=False, separators=(",", ":"))
